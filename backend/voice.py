"""
Aerix desktop voice safety-lock controller.

Recognizes only the two safety commands:
    Lock Aerix
    Unlock Aerix

The listener remains active while Aerix is locked.  Vosk grammar is used to
bias recognition toward the two commands, while a small set of common
recognition variants for "Aerix" is accepted.  A command is never triggered
from the word "lock" or "unlock" alone.
"""

from __future__ import annotations

import difflib
import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
from vosk import KaldiRecognizer, Model


class VoiceController:
    """Background microphone listener for Aerix lock/unlock commands."""

    # Run adaptive gain in the recognition worker, never in PortAudio's
    # lightweight callback. Values are normalized PCM RMS levels.
    _AGC_TARGET_RMS = 4200.0
    _AGC_MAX_GAIN = 12.0
    _AGC_ATTACK = 0.45
    _AGC_RELEASE = 0.18
    _NOISE_GATE_MIN_RMS = 55.0
    _NOISE_GATE_RATIO = 1.6
    _NOISE_GATE_FLOOR = 0.35
    _SPEECH_HANGOVER_SECONDS = 0.28
    _NOISE_CALIBRATION_SAMPLES = int(16000 * 0.35)

    # Vosk is much more likely to get the product name right when the grammar
    # contains plausible phonetic/word-boundary variants.
    _GRAMMAR = [
        "lock aerix",
        "unlock aerix",
        "lock aeryx",
        "unlock aeryx",
        "lock aeris",
        "unlock aeris",
        "lock arix",
        "unlock arix",
        "lock airix",
        "unlock airix",
        "lock erix",
        "unlock erix",
        "lock eric",
        "unlock eric",
        "lock aries",
        "unlock aries",
        "lock a risk",
        "unlock a risk",
        "lock a ricks",
        "unlock a ricks",
        # Narrowly cover the exact product-name confusion reported in the
        # microphone test. These remain complete two-word command phrases.
        "lock headaches",
        "unlock headaches",
    ]

    _AERIX_VARIANTS = {
        "aerix",
        "aeryx",
        "aeris",
        "arix",
        "erix",
        "eric",
        "aries",
        "a risk",
        "a ricks",
        "airix",
        "aerics",
        "aeric",
        "headache",
        "headaches",
    }
    _PARTIAL_AERIX_PREFIXES = {"a", "ae", "aer", "aeri"}
    _SEGMENT_PAIR_TIMEOUT = 2.5

    def __init__(
        self,
        lock_state_getter: Optional[Callable[[], bool]] = None,
        lock_state_setter: Optional[Callable[[bool], None]] = None,
        **kwargs,
    ):
        # Accept common keyword aliases so this remains compatible with the
        # already-integrated launcher/main.py.
        self._get_locked = (
            lock_state_getter
            or kwargs.get("get_locked")
            or kwargs.get("locked_getter")
        )
        self._set_locked = (
            lock_state_setter
            or kwargs.get("set_locked")
            or kwargs.get("locked_setter")
        )

        self.enabled = False
        self.last_command = ""
        self.last_recognized = ""
        self._pending_action = None
        self._pending_action_at = 0.0

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stream = None
        self._model = None
        self._model_path = None
        self._device = None
        self._native_samplerate = 16000
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=64)
        self._audio_callbacks = 0
        self._input_overflows = 0
        self._queue_drops = 0
        self._noise_floor_rms = 40.0
        self._noise_calibration_remaining = self._NOISE_CALIBRATION_SAMPLES
        self._noise_calibration_levels = []
        self._agc_gain = 1.0
        self._speech_active_until = 0.0
        self._gain_rms_before_total = 0.0
        self._gain_rms_after_total = 0.0
        self._gain_chunks = 0
        self._gain_peak = 1.0
        self._start_lock = threading.Lock()
        self._startup_event = threading.Event()
        self._startup_error = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(
        self,
        lock_state_getter: Optional[Callable[[], bool]] = None,
        lock_state_setter: Optional[Callable[[bool], None]] = None,
        **kwargs,
    ):
        # Serialize startup so concurrent callers cannot create duplicate
        # microphone streams or recognition workers.
        with self._start_lock:
            return self._start_once(lock_state_getter, lock_state_setter, **kwargs)

    def _start_once(
        self,
        lock_state_getter: Optional[Callable[[], bool]] = None,
        lock_state_setter: Optional[Callable[[bool], None]] = None,
        **kwargs,
    ):
        """Start the listener once. Fail gracefully if voice is unavailable."""
        if lock_state_getter is not None:
            self._get_locked = lock_state_getter
        if lock_state_setter is not None:
            self._set_locked = lock_state_setter
        if kwargs.get("get_locked") is not None:
            self._get_locked = kwargs["get_locked"]
        if kwargs.get("set_locked") is not None:
            self._set_locked = kwargs["set_locked"]

        if self.enabled and self._thread and self._thread.is_alive():
            return True

        if self._set_locked is None:
            print("VOICE: no lock-state setter configured; listener not started.")
            return False

        try:
            self._model_path = self._find_model()
            print(f"VOICE: loading Vosk model: {self._model_path}")
            self._model = Model(str(self._model_path))
            print("VOICE: Vosk model loaded successfully.")

            self._device = self._resolve_device(
                os.environ.get("AERIX_VOICE_DEVICE", "").strip()
            )
            self._native_samplerate = self._choose_samplerate(self._device)

            self._stop_event.clear()
            self._startup_event.clear()
            self._startup_error = None
            self._audio_callbacks = 0
            self._input_overflows = 0
            self._queue_drops = 0
            self._noise_floor_rms = 40.0
            self._noise_calibration_remaining = self._NOISE_CALIBRATION_SAMPLES
            self._noise_calibration_levels = []
            self._agc_gain = 1.0
            self._speech_active_until = 0.0
            self._gain_rms_before_total = 0.0
            self._gain_rms_after_total = 0.0
            self._gain_chunks = 0
            self._gain_peak = 1.0
            self._pending_action = None
            self._pending_action_at = 0.0
            self.enabled = True
            self._thread = threading.Thread(
                target=self._listen_loop,
                name="AerixVoiceListener",
                daemon=True,
            )
            self._thread.start()

            if not self._startup_event.wait(timeout=8):
                raise TimeoutError("microphone or Vosk recognizer startup timed out")
            if self._startup_error is not None:
                raise RuntimeError(str(self._startup_error))

            print(
                "VOICE: listener started "
                f"(device={self._device!r}, native_rate={self._native_samplerate})"
            )
            return True
        except Exception as exc:
            self.enabled = False
            self._stop_event.set()
            self._cleanup_stream()
            thread = self._thread
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=2)
            if thread is None or not thread.is_alive():
                self._thread = None
                self._model = None
            print(f"VOICE: listener unavailable: {type(exc).__name__}: {exc}")
            return False

    def stop(self):
        was_running = self.enabled or self._thread is not None
        self.enabled = False
        self._stop_event.set()
        self._cleanup_stream()

        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
        if thread and thread.is_alive():
            print("VOICE: listener shutdown is still waiting for the audio worker.")
        else:
            self._thread = None
            self._model = None
            if was_running:
                print("VOICE: listener stopped cleanly.")

    # ------------------------------------------------------------------
    # Model/device setup
    # ------------------------------------------------------------------

    def _find_model(self) -> Path:
        candidates = []

        env_path = os.environ.get("AERIX_VOSK_MODEL", "").strip()
        if env_path:
            candidates.append(Path(env_path))

        here = Path(__file__).resolve()
        backend_dir = here.parent
        extracted_root = backend_dir.parent

        candidates.extend(
            [
                Path.cwd() / "models" / "vosk-model-small-en-us-0.15",
                extracted_root / "models" / "vosk-model-small-en-us-0.15",
                backend_dir / "models" / "vosk-model-small-en-us-0.15",
                extracted_root.parent / "models" / "vosk-model-small-en-us-0.15",
            ]
        )
        # The source checkout keeps the shared model beside TouchlessMouse2,
        # above TouchlessMouse_/Mouse_updated (1)/Mouse_extracted.
        if len(extracted_root.parents) >= 3:
            candidates.append(
                extracted_root.parents[2] / "models" / "vosk-model-small-en-us-0.15"
            )

        for path in candidates:
            if path.is_dir():
                return path

        raise FileNotFoundError(
            "Vosk model not found. Expected "
            "'models/vosk-model-small-en-us-0.15' or set AERIX_VOSK_MODEL."
        )

    @staticmethod
    def _resolve_device(value: str):
        if not value:
            return None

        try:
            index = int(value)
            if index < 0:
                raise RuntimeError(f"invalid microphone device index: {index}")
            info = sd.query_devices(index, "input")
            if int(info.get("max_input_channels", 0)) < 1:
                raise RuntimeError(f"device {index} has no input channels")
            return index
        except ValueError:
            pass

        devices = sd.query_devices()
        wanted = value.casefold()
        candidates = []
        for index, info in enumerate(devices):
            name = str(info.get("name", ""))
            if wanted in name.casefold() and int(info.get("max_input_channels", 0)) > 0:
                candidates.append((index, name))

        exact = [index for index, name in candidates if wanted == name.strip().casefold()]
        matches = exact or [index for index, _ in candidates]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            devices_text = ", ".join(f"{index}: {devices[index]['name']}" for index in matches)
            raise RuntimeError(f"microphone device name is ambiguous: {value!r} ({devices_text})")

        raise RuntimeError(f"microphone device not found: {value!r}")

    @staticmethod
    def _choose_samplerate(device) -> int:
        # Prefer the device's native/default rate. The listener resamples to
        # Vosk's 16 kHz internally.
        if device is not None:
            info = sd.query_devices(device, "input")
        else:
            info = sd.query_devices(None, "input")

        rate = int(round(float(info.get("default_samplerate") or 16000)))
        if rate < 8000:
            rate = 16000
        return rate

    # ------------------------------------------------------------------
    # Audio / recognition
    # ------------------------------------------------------------------

    def _listen_loop(self):
        try:
            self._stream = sd.RawInputStream(
                samplerate=self._native_samplerate,
                # Let PortAudio select a backend-friendly callback size. A
                # fixed 4000-frame block can overrun on some Windows drivers.
                blocksize=0,
                device=self._device,
                dtype="int16",
                channels=1,
                latency="high",
                callback=self._audio_callback,
            )
            self._stream.start()

            recognizer = KaldiRecognizer(
                self._model,
                16000,
                json.dumps(self._GRAMMAR),
            )
            recognizer.SetWords(False)

            print(
                "VOICE: microphone opened and Vosk recognizer initialized "
                f"(device={self._device!r}, native_rate={self._native_samplerate}, Vosk_rate=16000)."
            )
            self._startup_event.set()

            while not self._stop_event.is_set():
                try:
                    raw = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                audio_16k = self._resample_to_16k(raw, self._native_samplerate)
                audio_16k = self._normalize_audio(audio_16k)

                if recognizer.AcceptWaveform(audio_16k):
                    result = json.loads(recognizer.Result())
                    text = self._normalize(result.get("text", ""))
                    if text:
                        self.last_recognized = text
                        print(f"VOICE: recognized '{text}'")
                        command = self._command_from_text(text)
                        if command is None:
                            command = self._command_from_segment(text)
                        else:
                            self._pending_action = None
                        if command:
                            self._apply_command(command)

        except Exception as exc:
            if not self._startup_event.is_set():
                self._startup_error = exc
                self._startup_event.set()
            print(f"VOICE: listener stopped: {type(exc).__name__}: {exc}")
        finally:
            self.enabled = False
            if self._audio_callbacks:
                print(
                    "VOICE: audio stats "
                    f"callbacks={self._audio_callbacks}, "
                    f"input_overflows={self._input_overflows}, "
                    f"queue_drops={self._queue_drops}, "
                    f"mean_rms_before={self._mean_rms(self._gain_rms_before_total)}, "
                    f"mean_rms_after={self._mean_rms(self._gain_rms_after_total)}, "
                    f"peak_gain={self._gain_peak:.1f}x."
                )
            self._cleanup_stream()

    def _audio_callback(self, indata, frames, time_info, status):
        if self._stop_event.is_set():
            return

        self._audio_callbacks += 1
        if status and getattr(status, "input_overflow", False):
            self._input_overflows += 1

        try:
            self._queue.put_nowait(bytes(indata))
        except queue.Full:
            # Drop old audio rather than blocking PortAudio's callback.
            try:
                self._queue.get_nowait()
                self._queue_drops += 1
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(bytes(indata))
            except queue.Full:
                pass

    @staticmethod
    def _resample_to_16k(raw: bytes, source_rate: int) -> bytes:
        if source_rate == 16000:
            return raw

        samples = np.frombuffer(raw, dtype=np.int16)
        if samples.size == 0:
            return raw

        target_len = max(1, int(round(samples.size * 16000 / source_rate)))
        source_x = np.linspace(0.0, 1.0, samples.size, endpoint=False)
        target_x = np.linspace(0.0, 1.0, target_len, endpoint=False)
        resampled = np.interp(target_x, source_x, samples).astype(np.int16)
        return resampled.tobytes()

    def _mean_rms(self, total: float) -> int:
        if not self._gain_chunks:
            return 0
        return int(round(total / self._gain_chunks))

    def _normalize_audio(self, raw: bytes) -> bytes:
        """Apply bounded adaptive gain and a soft noise gate to mono PCM."""
        samples_i16 = np.frombuffer(raw, dtype=np.int16)
        if samples_i16.size == 0:
            return raw

        samples = samples_i16.astype(np.float32)
        rms = float(np.sqrt(np.mean(samples * samples)))
        peak = float(np.max(np.abs(samples)))

        if self._noise_calibration_remaining > 0:
            # Estimate the room/microphone floor from the first short buffer
            # of normal background audio before applying automatic gain.
            self._noise_calibration_levels.append(rms)
            self._noise_calibration_remaining -= samples_i16.size
            if self._noise_calibration_remaining <= 0:
                self._noise_floor_rms = max(
                    12.0,
                    float(np.percentile(self._noise_calibration_levels, 30)),
                )
            self._gain_rms_before_total += rms
            self._gain_rms_after_total += rms
            self._gain_chunks += 1
            return raw

        gate_threshold = max(
            self._NOISE_GATE_MIN_RMS,
            self._noise_floor_rms * self._NOISE_GATE_RATIO,
        )

        if rms >= gate_threshold:
            desired_gain = min(
                self._AGC_MAX_GAIN,
                self._AGC_TARGET_RMS / max(rms, 1.0),
            )
            # Rise promptly for quiet speech. Reduce faster after a sudden
            # loud syllable so the next block quickly regains headroom.
            smoothing = self._AGC_ATTACK if desired_gain >= self._agc_gain else 0.55
            self._agc_gain += (desired_gain - self._agc_gain) * smoothing
            self._speech_active_until = time.monotonic() + self._SPEECH_HANGOVER_SECONDS
            gate = 1.0
        elif time.monotonic() < self._speech_active_until:
            # Hold the gate open briefly through quiet consonants and spaces
            # between words, without changing the recent speech gain.
            gate = 1.0
        else:
            # Track the local quiet level without following upward spikes.
            # The gate is deliberately soft so low-energy consonants and
            # speech tails are attenuated gradually, not chopped off.
            observed_floor = min(rms, self._noise_floor_rms * 1.5)
            self._noise_floor_rms = max(
                12.0,
                self._noise_floor_rms * 0.96 + observed_floor * 0.04,
            )
            self._agc_gain += (1.0 - self._agc_gain) * self._AGC_RELEASE
            gate = min(
                max(self._NOISE_GATE_FLOOR, min(1.0, rms / gate_threshold)),
                0.75 / max(1.0, self._agc_gain),
            )

        gain = self._agc_gain
        if peak > 0.0:
            # Keep sample peaks below full scale instead of hard-clipping.
            gain = min(gain, 30000.0 / (peak * gate))

        processed = np.rint(samples * gain * gate).astype(np.int16)
        output = processed.astype(np.float32)
        output_rms = float(np.sqrt(np.mean(output * output)))
        self._gain_rms_before_total += rms
        self._gain_rms_after_total += output_rms
        self._gain_chunks += 1
        self._gain_peak = max(self._gain_peak, gain)
        return processed.tobytes()

    # ------------------------------------------------------------------
    # Command matching
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(text: str) -> str:
        cleaned = "".join(
            ch.lower() if (ch.isalnum() or ch.isspace()) else " "
            for ch in text
        )
        return " ".join(cleaned.split())

    @classmethod
    def _aerix_match(cls, phrase: str) -> bool:
        phrase = " ".join(phrase.split())
        if phrase in cls._AERIX_VARIANTS:
            return True

        # Fuzzy matching applies only to a whole, reasonably long product-name
        # token. Short fragments such as "are" or "aer" cannot unlock Aerix.
        if len(phrase) < 4 or len(phrase) > 8:
            return False
        score = difflib.SequenceMatcher(None, phrase, "aerix").ratio()
        return score >= 0.80

    @classmethod
    def _command_from_text(cls, text: str) -> Optional[str]:
        words = text.split()
        if not words:
            return None

        # Keep the action at the start of the transcript so ordinary speech
        # that merely mentions a command later cannot activate the lock.
        # Vosk sometimes repeats the command and leaves the second product
        # name partial (for example, "unlock aries unlock a").
        action = words[0]
        if action not in {"lock", "unlock"}:
            return None

        for variant_length in (1, 2):
            end = 1 + variant_length
            if end > len(words):
                continue
            phrase = " ".join(words[1:end])
            if not cls._aerix_match(phrase):
                continue

            trailing = words[end:]
            if not trailing:
                return action
            if (
                len(trailing) == 2
                and trailing[0] == action
                and trailing[1] in cls._PARTIAL_AERIX_PREFIXES
            ):
                return action
        return None

    def _command_from_segment(self, text: str) -> Optional[str]:
        """Join Vosk's split action/name results without accepting action alone."""
        now = time.monotonic()
        if (
            self._pending_action
            and now - self._pending_action_at > self._SEGMENT_PAIR_TIMEOUT
        ):
            self._pending_action = None

        if text in {"lock", "unlock"}:
            self._pending_action = text
            self._pending_action_at = now
            print(f"VOICE: awaiting Aerix name after '{text}'.")
            return None

        action = self._pending_action
        self._pending_action = None
        if action and self._aerix_match(text):
            return action
        return None

    def _apply_command(self, command: str):
        if self._set_locked is None:
            return

        locked = command == "lock"

        try:
            self._set_locked(locked)
            self.last_command = "Lock Aerix" if locked else "Unlock Aerix"
            print(f"VOICE COMMAND: {self.last_command}")
        except Exception as exc:
            print(f"VOICE: failed to update lock state: {type(exc).__name__}: {exc}")

    def _cleanup_stream(self):
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
