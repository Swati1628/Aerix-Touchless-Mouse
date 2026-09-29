"""Local scikit-learn URL risk classifier trained on the bundled synthetic set."""
from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunsplit

import joblib
import sklearn

MODEL_PATH = Path(__file__).with_name("models") / "url_safety_model.joblib"
RISK_LABELS = {"SAFE", "SUSPICIOUS", "DANGEROUS"}
RISK_WORDS = (
    "login", "verify", "account", "password", "wallet", "secure", "update",
    "signin", "confirm", "billing", "invoice", "bank", "support", "recover",
)
SUSPICIOUS_TLDS = {"click", "country", "gq", "kim", "link", "mom", "rest", "top", "work", "zip"}
TRACKING_QUERY_KEYS = {"gclid", "dclid", "gbraid", "wbraid", "fbclid", "msclkid"}


def _strip_tracking_parameters(url: str) -> str:
    """Ignore standard analytics parameters when scoring destination risk."""
    try:
        parsed = urlparse(url)
        query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                 if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS]
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), parsed.fragment))
    except (TypeError, ValueError):
        return url


def _normalize_url_batch(urls):
    """Apply the same benign-tracking cleanup during training and inference."""
    return [_strip_tracking_parameters(str(url)) for url in urls]


def url_features(urls):
    """Return inexpensive numeric indicators for URL strings."""
    rows = []
    for value in urls:
        raw = str(value).strip().lower()
        try:
            parsed = urlparse(raw)
            host = (parsed.hostname or "").rstrip(".")
            port = parsed.port
        except ValueError:
            parsed, host, port = urlparse(""), "", None
        labels = host.split(".") if host else []
        path_query = f"{parsed.path}?{parsed.query}".lower()
        try:
            is_ip = float(bool(host) and ipaddress.ip_address(host.strip("[]")) is not None)
        except ValueError:
            is_ip = 0.0
        digit_count = sum(character.isdigit() for character in host)
        alpha_count = sum(character.isalpha() for character in host)
        keyword_count = sum(word in raw for word in RISK_WORDS)
        rows.append({
            "url_length": min(len(raw), 500) / 100.0,
            "host_length": min(len(host), 200) / 50.0,
            "subdomain_count": max(0, len(labels) - 2),
            "hyphen_count": host.count("-"),
            "digit_ratio": digit_count / max(1, len(host)),
            "keyword_count": keyword_count,
            "is_https": float(parsed.scheme == "https"),
            "is_http": float(parsed.scheme == "http"),
            "is_ip": is_ip,
            "has_userinfo": float("@" in raw),
            "is_punycode": float(any(label.startswith("xn--") for label in labels)),
            "has_encoded_chars": float(bool(re.search(r"%[0-9a-f]{2}", raw))),
            "has_executable_suffix": float(any(path_query.split("?", 1)[0].endswith(ext) for ext in (".exe", ".msi", ".apk", ".bat", ".ps1", ".scr", ".js"))),
            "has_suspicious_tld": float(bool(labels) and labels[-1] in SUSPICIOUS_TLDS),
            "has_nonstandard_port": float(port is not None and port not in {80, 443}),
            "contains_query": float(bool(parsed.query)),
            "digit_alpha_mix": float(digit_count > 0 and alpha_count > 0),
        })
    return rows


def build_model():
    """Build a compact character n-gram plus engineered-feature classifier."""
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import FeatureUnion, Pipeline
    from sklearn.preprocessing import FunctionTransformer
    from sklearn.linear_model import LogisticRegression

    features = FeatureUnion([
        ("characters", TfidfVectorizer(
            analyzer="char", ngram_range=(2, 5), min_df=1,
            lowercase=True, sublinear_tf=True, max_features=12000,
        )),
        ("url_signals", Pipeline([
            ("extract", FunctionTransformer(url_features, validate=False)),
            ("dict", DictVectorizer()),
        ])),
    ])
    return Pipeline([
        ("normalize", FunctionTransformer(_normalize_url_batch, validate=False)),
        ("features", features),
        ("classifier", LogisticRegression(
            class_weight="balanced", max_iter=1000, C=2.0, random_state=42,
        )),
    ])


class URLClassifier:
    """Loads one local model and classifies URLs without network access."""
    def __init__(self, model_path: Path = MODEL_PATH):
        if not model_path.is_file():
            raise FileNotFoundError(
                f"URL safety model missing at {model_path}; run `python -m backend.train_url_model`."
            )
        bundle = joblib.load(model_path)
        trained_version = bundle.get("scikit_learn_version")
        if trained_version and trained_version != sklearn.__version__:
            raise RuntimeError(
                f"URL safety model uses scikit-learn {trained_version}; installed version is "
                f"{sklearn.__version__}. Run `python -m backend.train_url_model` to retrain it."
            )
        self.model = bundle["model"]
        self.training_samples = bundle.get("training_samples", 0)

    def classify(self, url: str) -> dict:
        probabilities = self.model.predict_proba([url])[0]
        classes = self.model.named_steps["classifier"].classes_
        probability_by_label = {label: float(probability) for label, probability in zip(classes, probabilities)}
        label = max(probability_by_label, key=probability_by_label.get)
        confidence = probability_by_label[label]
        # Conservative local policy: only high-confidence SAFE is allowed.
        if label == "SAFE" and confidence >= 0.55:
            risk = "safe"
            allowed = True
            reason = "URL characteristics are closest to the trained safe examples"
        elif label == "DANGEROUS" and confidence >= 0.60:
            risk = "dangerous"
            allowed = False
            reason = "ML classifier found multiple high-risk URL characteristics"
        else:
            risk = "suspicious"
            allowed = False
            reason = "ML classifier found suspicious or uncertain URL characteristics"
        return {
            "allowed": allowed,
            "risk": risk,
            "confidence": confidence,
            "reason": reason,
            "ai_detected": True,
            "model_label": label,
        }
