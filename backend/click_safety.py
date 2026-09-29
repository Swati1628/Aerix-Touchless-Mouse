"""Privacy-preserving safety checks for gesture-triggered clicks."""
from __future__ import annotations

import ipaddress
import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse, urlsplit, urlunsplit
from .url_classifier import URLClassifier
from .threat_intelligence import ThreatIntelligence

EXECUTABLE_EXTENSIONS = {".apk", ".bat", ".cmd", ".com", ".dll", ".exe", ".jar", ".js", ".msi", ".ps1", ".scr", ".vbs"}
SUSPICIOUS_TLDS = {"click", "country", "gq", "kim", "link", "mom", "rest", "top", "work", "zip"}
PHISHING_TERMS = {"account-verify", "login-verify", "password-reset", "secure-login", "wallet-verify"}
RESULT_TTL_SECONDS = 30.0
TARGET_TTL_SECONDS = RESULT_TTL_SECONDS
PARENTAL_FILTER_PATH = Path(__file__).with_name("parental_filter.json")

@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    reason: Optional[str] = None
    inspected: bool = False
    risk: str = "unknown"
    confidence: float = 0.0
    ai_detected: bool = False
    threat_intelligence: Optional[dict] = None

class ClickSafety:
    """Checks reported same-page links locally; unknown desktop targets pass."""
    def __init__(self):
        self._lock = threading.Lock()
        self._target_url: Optional[str] = None
        self._target_time = 0.0
        self._target_revision = 0
        self._pending: dict[str, int] = {}
        self.last_block: Optional[dict] = None
        self._results = {}
        self._filter = self._load_filter()
        self._classifier = URLClassifier()
        self._threat_intelligence = ThreatIntelligence()

    @staticmethod
    def _load_filter() -> dict:
        try:
            with PARENTAL_FILTER_PATH.open("r", encoding="utf-8") as config_file:
                config = json.load(config_file)
            return config if isinstance(config, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def inspect_url(self, url: str) -> dict:
        """Inspect a URL string locally and reuse its recent decision."""
        original_url = url
        url = self._normalize_url(url)
        try:
            parsed = urlsplit(url)
            print(f"[Touchless API DEBUG] original_url: {original_url}")
            print(f"[Touchless API DEBUG] normalized_url: {url}")
            print(f"[Touchless API DEBUG] hostname: {parsed.hostname or ''}")
            print(f"[Touchless API DEBUG] pathname: {parsed.path}")
            print(f"[Touchless API DEBUG] query: {parsed.query}")
        except ValueError:
            print(f"[Touchless API DEBUG] URL parse failed after normalization: {url}")
        policy_decision = self._custom_site_block_decision(url, self._filter)
        now = time.monotonic()
        safe_url = url.encode("ascii", "backslashreplace").decode("ascii")
        with self._lock:
            if policy_decision is not None:
                # A current hard-block policy must replace any older SAFE cache
                # result and take precedence over every other inspection source.
                decision = policy_decision
                cache_hit = False
                self._target_revision += 1
                revision = self._target_revision
                self._target_url = url
                self._target_time = now
                self._pending.pop(url, None)
                self._results[url] = (now, decision)
            else:
                cached = self._results.get(url)
                cache_hit = bool(cached and now - cached[0] <= RESULT_TTL_SECONDS)
                if cache_hit:
                    decision = cached[1]
                    self._target_revision += 1
                    revision = self._target_revision
                    self._target_url = url
                    self._target_time = now
                else:
                    self._target_revision += 1
                    revision = self._target_revision
                    self._target_url = url
                    self._target_time = now
                    self._pending[url] = revision
        if not cache_hit and policy_decision is None:
            print(f"[AI SAFETY] URL detected: {safe_url}")
            print(f"[AI SAFETY] Analyzing: {safe_url}")
            try:
                decision = self._evaluate_url(url, self._filter)
            except Exception:
                with self._lock:
                    if self._pending.get(url) == revision:
                        self._pending.pop(url, None)
                raise
            with self._lock:
                existing = self._results.get(url)
                if not existing or time.monotonic() - existing[0] > RESULT_TTL_SECONDS:
                    self._results[url] = (time.monotonic(), decision)
                else:
                    decision = existing[1]
                if self._pending.get(url) == revision:
                    self._pending.pop(url, None)
                    if self._target_revision == revision and self._target_url == url:
                        self._target_time = time.monotonic()
                if len(self._results) > 256:
                    now = time.monotonic()
                    self._results = {key: value for key, value in self._results.items()
                                     if now - value[0] <= RESULT_TTL_SECONDS}
        if not cache_hit:
            print(f"[AI SAFETY] Classification: {decision.risk.upper()}")
            print(f"[AI SAFETY] Confidence: {decision.confidence:.2f}")
        reason = decision.reason or "URL appears safe"
        parental_result = (reason if reason.startswith("Parental restriction:")
                           or reason == "Blocked by Aerix custom security policy"
                           else "no matching parental-filter rule")
        classifier_result = ({"allowed": decision.allowed, "risk": decision.risk,
                              "confidence": decision.confidence, "ai_detected": decision.ai_detected,
                              "reason": reason}
                             if decision.ai_detected else "not run or a deterministic rule decided first")
        print(f"[Touchless API DEBUG] classifier result: {classifier_result}")
        print(f"[Touchless API DEBUG] threat-intelligence result: {decision.threat_intelligence or {}}")
        print(f"[Touchless API DEBUG] parental-filter result: {parental_result}")
        print(f"[Touchless API DEBUG] final allowed: {decision.allowed}")
        print(f"[Touchless API DEBUG] final risk: {decision.risk}")
        print(f"[Touchless API DEBUG] final reason: {reason}")
        return {"allowed": decision.allowed,
                "risk": decision.risk,
                "reason": reason,
                "confidence": decision.confidence,
                "ai_detected": decision.ai_detected,
                "threat_intelligence": decision.threat_intelligence or {},
                "phishtank": (decision.threat_intelligence or {}).get("phishtank", {"status": "not_checked"}),
                "virustotal": (decision.threat_intelligence or {}).get("virustotal", {"status": "not_checked"}),
                "cached": cache_hit}

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize URLs for stable cache keys without fetching the target."""
        raw = url.strip()
        try:
            parsed = urlsplit(raw)
            if not parsed.scheme or not parsed.netloc:
                return raw
            hostname = (parsed.hostname or "").lower().rstrip(".")
            if not hostname:
                return raw
            userinfo = ""
            if parsed.username is not None:
                userinfo = parsed.username
                if parsed.password is not None:
                    userinfo += ":" + parsed.password
                userinfo += "@"
            try:
                port = parsed.port
            except ValueError:
                return raw
            default_port = (parsed.scheme.lower() == "http" and port == 80) or (
                parsed.scheme.lower() == "https" and port == 443
            )
            host_text = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
            netloc = userinfo + host_text + (f":{port}" if port and not default_port else "")
            return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))
        except (TypeError, ValueError):
            return raw

    @staticmethod
    def _custom_site_block_decision(raw_url: str, config: dict) -> Optional[SafetyDecision]:
        """Match configured service-name hostname labels before reputation checks."""
        try:
            parsed = urlsplit(raw_url)
            if parsed.scheme.lower() not in {"http", "https"}:
                return None
            hostname = unquote(parsed.hostname or "").lower().rstrip(".")
            labels = {label for label in hostname.split(".") if label}
        except (TypeError, ValueError):
            return None
        names = config.get("blocked_site_names", []) if isinstance(config, dict) else []
        if not isinstance(names, list):
            return None
        blocked_name = next((name.strip().lower().lstrip(".").rstrip(".") for name in names
                             if isinstance(name, str) and name.strip()
                             and name.strip().lower().lstrip(".").rstrip(".") in labels), None)
        if blocked_name is None:
            return None
        return SafetyDecision(False, "Blocked by Aerix custom security policy", True,
                              "dangerous", 1.0)

    def report_target(self, url: Optional[str]) -> None:
        if isinstance(url, str) and url:
            self.inspect_url(url)
            return
        with self._lock:
            self._target_revision += 1
            self._target_url = None
            self._target_time = time.monotonic()

    def evaluate_click(self) -> SafetyDecision:
        with self._lock:
            url, fresh = self._target_url, time.monotonic() - self._target_time <= TARGET_TTL_SECONDS
            unknown_policy = self._filter.get("unknown_target_policy", "allow")
            if url and fresh:
                if self._pending.get(url) == self._target_revision:
                    return SafetyDecision(False, "AI URL inspection is still pending", inspected=False, risk="unknown")
                cached = self._results.get(url)
                if cached and time.monotonic() - cached[0] <= RESULT_TTL_SECONDS:
                    return cached[1]
        if unknown_policy == "block":
            return SafetyDecision(False, "Unable to inspect target", inspected=False, risk="unknown")
        return SafetyDecision(True, "No fresh browser target is available", inspected=False, risk="unknown")

    def block(self, decision: SafetyDecision) -> None:
        with self._lock:
            self.last_block = {
                "reason": decision.reason or "Potentially dangerous destination",
                "risk": decision.risk,
                "confidence": decision.confidence,
                "ai_detected": decision.ai_detected,
                "timestamp": time.time(),
            }
        print(f"[AI SAFETY] CLICK BLOCKED: {decision.risk.upper()} ({decision.confidence:.2f}) - {decision.reason}")

    def dismiss(self) -> None:
        with self._lock:
            self.last_block = None

    def status(self) -> dict:
        with self._lock:
            warning = dict(self.last_block) if self.last_block else None
            inspected = bool(self._target_url) and time.monotonic() - self._target_time <= TARGET_TTL_SECONDS
        return {"enabled": True, "mode": "local", "status": "ACTIVE" if inspected else "LIMITED", "message": "Inspecting hovered links locally" if inspected else "Desktop target inspection is unavailable", "warning": warning}

    def _evaluate_url(self, raw_url: str, parental_filter: Optional[dict] = None) -> SafetyDecision:
        try:
            parsed = urlparse(raw_url)
            hostname = (parsed.hostname or "").lower().rstrip(".")
        except (TypeError, ValueError):
            return SafetyDecision(False, "Malformed or suspicious link", True, "dangerous", 1.0)
        if parsed.scheme.lower() == "safety-test" and hostname == "simulated-phishing":
            return SafetyDecision(False, "Simulated phishing target", True, "dangerous", 1.0)
        if parsed.scheme.lower() in {"file", "javascript", "ms-msdt"}:
            return SafetyDecision(False, "Potentially dangerous local or script link", True, "dangerous", 1.0)
        if parsed.scheme.lower() not in {"http", "https"} or not hostname:
            return SafetyDecision(False, "Unsupported or suspicious link destination", True, "suspicious", 1.0)
        config = parental_filter or {}
        custom_block = self._custom_site_block_decision(raw_url, config)
        if custom_block is not None:
            return custom_block
        blocked_domains = config.get("blocked_domains", [])
        if isinstance(blocked_domains, list) and any(
            hostname == domain.lower().lstrip(".") or hostname.endswith("." + domain.lower().lstrip("."))
            for domain in blocked_domains if isinstance(domain, str) and domain.strip()
        ):
            matched_domain = next(domain for domain in blocked_domains if isinstance(domain, str) and domain.strip()
                                  and (hostname == domain.lower().lstrip(".")
                                       or hostname.endswith("." + domain.lower().lstrip("."))))
            print(f"[Touchless API DEBUG] parental-filter matched domain: {matched_domain}")
            return SafetyDecision(False, "Parental restriction: blocked domain", True, "blocked", 1.0)
        blocked_categories = config.get("blocked_categories", [])
        category_domains = config.get("category_domains", {})
        if isinstance(blocked_categories, list) and isinstance(category_domains, dict):
            for category in blocked_categories:
                domains = category_domains.get(category, [])
                if isinstance(category, str) and isinstance(domains, list) and any(
                    isinstance(domain, str) and domain.strip() and
                    (hostname == domain.lower().lstrip(".") or hostname.endswith("." + domain.lower().lstrip(".")))
                    for domain in domains
                ):
                    print(f"[Touchless API DEBUG] parental-filter matched category: {category}")
                    return SafetyDecision(False, f"Parental restriction: blocked {category} category", True, "blocked", 1.0)
        if parsed.username or parsed.password or hostname.startswith("xn--") or ".xn--" in hostname:
            return SafetyDecision(False, "Possible phishing URL", True, "suspicious", 1.0)
        try:
            address = ipaddress.ip_address(hostname.strip("[]"))
            # The application's own local test UI legitimately uses 127.0.0.1.
            if address.is_loopback:
                return SafetyDecision(True, inspected=True, risk="safe", confidence=1.0)
            return SafetyDecision(False, "Possible phishing URL using a raw IP address", True, "dangerous", 1.0)
        except ValueError:
            pass
        if hostname.rsplit(".", 1)[-1] in SUSPICIOUS_TLDS and any(word in hostname for word in ("login", "verify", "secure", "account", "wallet")):
            return SafetyDecision(False, "Possible phishing URL", True, "suspicious", 1.0)
        decoded_path = unquote(parsed.path).lower()
        if any(decoded_path.endswith(extension) for extension in EXECUTABLE_EXTENSIONS):
            return SafetyDecision(False, "Dangerous executable or script download", True, "dangerous", 1.0)
        combined = f"{hostname}{decoded_path}"
        if any(term in combined for term in PHISHING_TERMS) and re.search(r"(?:login|verify|secure|account|wallet)", hostname):
            return SafetyDecision(False, "Possible phishing URL", True, "suspicious", 1.0)

        # These reputation lookups only send the URL string to the providers; they
        # never fetch, open, or submit the destination for scanning.
        try:
            intel = self._threat_intelligence.inspect(raw_url)
        except Exception as exc:
            print(f"[URL INTEL] Lookup failed safely: {type(exc).__name__}")
            intel = {
                "phishtank": {"status": "unavailable", "matched": False},
                "virustotal": {"status": "unavailable", "malicious": 0, "suspicious": 0},
                "cached": False,
            }
        phishtank = intel.get("phishtank", {})
        virustotal = intel.get("virustotal", {})
        print(f"[Touchless API DEBUG] threat-intelligence result: {intel}")
        if phishtank.get("matched"):
            return SafetyDecision(False, "Verified phishing URL reported by PhishTank", True,
                                  "dangerous", 1.0, False, intel)
        malicious = int(virustotal.get("malicious", 0) or 0)
        vt_suspicious = int(virustotal.get("suspicious", 0) or 0)
        print(f"[URL INTEL] PhishTank: {phishtank.get('status', 'not_checked')}; "
              f"VirusTotal: {virustotal.get('status', 'not_checked')}")
        if malicious > 0:
            return SafetyDecision(False, f"VirusTotal reports {malicious} malicious detection(s)", True,
                                  "dangerous", 1.0, False, intel)

        result = self._classifier.classify(raw_url)
        print(f"[Touchless API DEBUG] classifier result: {result}")
        if vt_suspicious > 0 and result["risk"] == "safe":
            return SafetyDecision(False, f"VirusTotal reports {vt_suspicious} suspicious detection(s)", True,
                                  "suspicious", 1.0, False, intel)
        return SafetyDecision(
            result["allowed"], result["reason"], True, result["risk"],
            result["confidence"], result["ai_detected"], intel,
        )
