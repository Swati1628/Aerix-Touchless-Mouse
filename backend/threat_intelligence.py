"""Small, cached URL reputation lookups. URLs are sent as data only; never fetched."""
from __future__ import annotations

import base64
import json
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv


load_dotenv()

class ThreatIntelligence:
    """Optional PhishTank and VirusTotal URL report lookups using stdlib HTTP."""

    CACHE_TTL = 300.0
    FAILURE_CACHE_TTL = 30.0
    REQUEST_TIMEOUT = 1.25
    MAX_RESPONSE_BYTES = 512 * 1024

    def __init__(self):
        self.phishtank_key = os.environ.get("PHISHTANK_APP_KEY", "").strip()
        self.virustotal_key = os.environ.get("VIRUSTOTAL_API_KEY", "").strip()
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict]] = {}
        self._last_request = {"phishtank": 0.0, "virustotal": 0.0}

    def inspect(self, url: str) -> dict:
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(url)
            if cached and now - cached[0] < self._cache_ttl(cached[1]):
                return {**cached[1], "cached": True}

        results = {
            "phishtank": self._phishtank(url),
            "virustotal": self._virustotal(url),
        }
        results["cached"] = False
        with self._lock:
            self._cache[url] = (time.monotonic(), results)
            if len(self._cache) > 512:
                now = time.monotonic()
                self._cache = {key: value for key, value in self._cache.items()
                               if now - value[0] < self._cache_ttl(value[1])}
        return results

    @classmethod
    def _cache_ttl(cls, result: dict) -> float:
        statuses = (result.get("phishtank", {}).get("status"),
                    result.get("virustotal", {}).get("status"))
        if any(status in {"unavailable", "rate_limited"} for status in statuses):
            return cls.FAILURE_CACHE_TTL
        return cls.CACHE_TTL

    def _reserve(self, source: str, minimum_interval: float) -> bool:
        with self._lock:
            now = time.monotonic()
            if now - self._last_request[source] < minimum_interval:
                return False
            self._last_request[source] = now
            return True

    @staticmethod
    def _json_request(request: Request) -> tuple[int, dict]:
        try:
            with urlopen(request, timeout=ThreatIntelligence.REQUEST_TIMEOUT) as response:
                payload = response.read(ThreatIntelligence.MAX_RESPONSE_BYTES + 1)
                if len(payload) > ThreatIntelligence.MAX_RESPONSE_BYTES:
                    return response.status, {}
                return response.status, json.loads(payload.decode("utf-8"))
        except HTTPError as exc:
            body = exc.read(ThreatIntelligence.MAX_RESPONSE_BYTES)
            try:
                return exc.code, json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return exc.code, {}
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            return 0, {}

    def _phishtank(self, url: str) -> dict:
        if not self._reserve("phishtank", 1.0):
            return {"status": "rate_limited", "matched": False}
        values = {"url": url, "format": "json"}
        if self.phishtank_key:
            values["app_key"] = self.phishtank_key
        request = Request(
            "https://checkurl.phishtank.com/checkurl/",
            data=urlencode(values).encode("ascii"),
            headers={"User-Agent": "TouchlessMouseURLSafety/1.0", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        status, body = self._json_request(request)
        if status == 200:
            if not isinstance(body, dict) or "results" not in body:
                return {"status": "unavailable", "matched": False}
            result = body.get("results")
            if not isinstance(result, dict):
                return {"status": "unavailable", "matched": False}
            def is_yes(value):
                return value is True or str(value).strip().lower() in {"yes", "y", "true", "1"}
            match = bool(is_yes(result.get("in_database")) and is_yes(result.get("verified"))
                         and is_yes(result.get("valid")))
            return {"status": "match" if match else "no_match", "matched": match}
        if status in {429, 509}:
            return {"status": "rate_limited", "matched": False}
        return {"status": "unavailable", "matched": False}

    def _virustotal(self, url: str) -> dict:
        if not self.virustotal_key:
            return {"status": "not_configured", "malicious": 0, "suspicious": 0}
        if not self._reserve("virustotal", 15.0):
            return {"status": "rate_limited", "malicious": 0, "suspicious": 0}
        url_id = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
        request = Request(
            f"https://www.virustotal.com/api/v3/urls/{url_id}",
            headers={"x-apikey": self.virustotal_key, "User-Agent": "TouchlessMouseURLSafety/1.0"},
            method="GET",
        )
        status, body = self._json_request(request)
        if status == 404:
            return {"status": "not_found", "malicious": 0, "suspicious": 0}
        if status in {429, 509}:
            return {"status": "rate_limited", "malicious": 0, "suspicious": 0}
        if status != 200:
            return {"status": "unavailable", "malicious": 0, "suspicious": 0}
        data = body.get("data", {}) if isinstance(body, dict) else {}
        attributes = data.get("attributes", {}) if isinstance(data, dict) else {}
        stats = attributes.get("last_analysis_stats", {}) if isinstance(attributes, dict) else {}
        if not isinstance(stats, dict):
            return {"status": "unavailable", "malicious": 0, "suspicious": 0}
        try:
            malicious = int(stats.get("malicious", 0) or 0)
            suspicious = int(stats.get("suspicious", 0) or 0)
        except (TypeError, ValueError):
            return {"status": "unavailable", "malicious": 0, "suspicious": 0}
        return {"status": "reported", "malicious": malicious, "suspicious": suspicious}
