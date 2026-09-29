# AI Gesture Mouse — FastAPI Version

Backend: FastAPI, MediaPipe Tasks Hand Landmarker, OpenCV, and PyAutoGUI.
Frontend: browser-native HTML, CSS, and JavaScript served directly by FastAPI.

## Setup

1. Install backend dependencies from this directory:

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. Ensure the MediaPipe model is present at:

   ```text
   models/hand_landmarker.task
   ```

3. In one terminal, start the backend:

   ```powershell
   python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
   ```

4. Open `http://127.0.0.1:8000/`.

FastAPI serves `Aeris/index.html` at `/`, `Aeris/script.js` at
`/static/script.js`, and `modern-frontend/index.css` at
`/modern-static/index.css`. The browser connects directly to the API,
WebSocket, and camera-stream endpoints. No Node.js, npm, React, Vite, or
separate frontend development server is required. The camera feed is displayed
in the browser; no OpenCV desktop window is opened.

Completed four-point calibration is saved to `calibration_points.json` and is
restored when the backend restarts. Starting or resetting calibration clears
the saved mapping until a new calibration completes.

## URL safety and threat intelligence

The Manifest V3 extension reports a changed hovered link to
`POST /api/safety/inspect`. FastAPI calls the existing `ClickSafety` engine,
which applies the parental filter and deterministic URL rules, then performs
cached PhishTank and optional VirusTotal reputation lookups and local ML
classification. This runs in the API request handler, outside the camera and
gesture loop. The existing `evaluate_click()` gate remains immediately before
PyAutoGUI click calls; while an inspection is pending it blocks that click.

PhishTank uses its URL check API with the URL submitted as data only. Set
`PHISHTANK_APP_KEY` to a registered application key for higher quotas; limited
unauthenticated lookups may also be available. VirusTotal, when configured,
uses its API v3 existing URL report endpoint only. It does not submit a URL for
scanning. Set `VIRUSTOTAL_API_KEY` in the environment running FastAPI; the key
is never sent to the extension. Copy `.env.example` as a reference, then set
environment variables in PowerShell before starting the server, for example:

```powershell
$env:PHISHTANK_APP_KEY = "your_phishtank_app_key"
$env:VIRUSTOTAL_API_KEY = "your_virustotal_api_key"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

VirusTotal's public API has a low request quota. The backend caches per-URL
intelligence for five minutes and spaces VT requests to avoid repeated quota
use. Results expose each source status (`reported`, `match`, `no_match`,
`not_found`, `not_configured`, `rate_limited`, or `unavailable`) so a failed
lookup is never reported as clean. Provider errors/timeouts fall back to
deterministic rules and the local classifier. `/api/safety/inspect` includes
`threat_intelligence`, `phishtank`, and `virustotal` fields.

The local scikit-learn classifier combines character n-grams with URL features
such as hostname/subdomain shape, length, digits, special characters, ports,
IP literals, schemes, encoding, TLD, and login/verification terms. Verified
PhishTank matches and VirusTotal malicious detections take precedence and are
blocked. Any suspicious/dangerous model or deterministic result is also
blocked; uncertain model predictions are not treated as safe.

The included `backend/data/url_training.csv` is a small, hand-curated synthetic
demonstration set. It contains reserved `.example`/`.test` targets and benign
public URL examples, not a downloaded threat feed. It is too small to establish
real-world detection accuracy. Logistic-regression probabilities are model
scores, not calibrated estimates of the chance a site is malicious. The current
fixed 20% synthetic holdout run scored 0.875; that is not a real-world accuracy
claim. The model does not establish that a site is illegal or fetch/open the
destination URL. Keep explicit restrictions in the parental filter and treat
the model as a lightweight warning layer, not a guarantee.

Install the added model dependency with the existing requirements command. The
trained model is included at `backend/models/url_safety_model.joblib`. To
rebuild it from the bundled synthetic data, run this from the project directory:

```powershell
python -m backend.train_url_model
```

The extension and FastAPI each cache decisions for 30 seconds; reputation
successful reputation responses use a separate five-minute cache; provider
failures and rate limits are cached for 30 seconds. The extension sends another
inspection request when the hovered link changes, not on every pointer event.
The content script cancels link activation while inspection is pending and for
any non-safe result. To load or refresh the extension, open
`chrome://extensions`, enable Developer mode, choose **Load unpacked**, and
select `browser_extension`; after code changes, press **Reload** and refresh
open web pages. Use the same steps at `edge://extensions` in Edge.

Safe smoke check: POST `{"url":"https://www.google.com"}` to
`http://127.0.0.1:8000/api/safety/inspect` and expect `risk: safe`. The bundled
`https://blocked-test.example/` target should return `risk: blocked`. For an
unlisted-pattern check, use the synthetic URL
`https://member-check-account.example.test/continue?ref=ZX91`; it should be
classified as suspicious by the trained model. Do not visit a real malicious
site.

The webcam/gesture loop is separate from model inference: URL inspection runs
on the FastAPI request path, while the existing click gate reads cached
decisions locally. If inspection is pending, the extension blocks the browser
link and asks the user to wait for the result before retrying. This small local
training set will miss unfamiliar attacks and may flag unusual benign URLs;
greater coverage requires carefully sourced labeled data and retraining.

The extension's warning identifies available intelligence sources. Hover and
click protection work on HTTP/HTTPS pages covered by the extension's existing
permissions. Load/reload instructions and the safe synthetic checks are below.

No real malicious site is opened or downloaded by this system. Threat
intelligence is imperfect, ML scores do not guarantee detection, providers can
be unavailable or rate limited, and no system detects every harmful URL. This
is URL safety screening; it does not determine legal status. A provider API key
was not available in this development environment, so authenticated live API
responses have not been verified here.

## Docker Compose

From the `TouchlessMouse_Final` directory, build the images with:

```powershell
docker compose build
```

Start the services with:

```powershell
docker compose up
```

The FastAPI application, including its browser-native frontend, is available
at `http://localhost:8000`. `calibration_points.json` is bind-mounted so
calibration data persists across container recreation.

### Windows host-resource limitation

The backend image is a Linux container. On Docker Desktop for Windows it cannot
use the Windows Media Foundation (`CAP_MSMF`) webcam backend or control the
Windows desktop mouse and keyboard through PyAutoGUI. The container is suitable
for web/API development and packaging, but run the backend natively on Windows
for functional webcam capture and host desktop mouse control.
