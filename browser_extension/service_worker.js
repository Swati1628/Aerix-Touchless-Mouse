const API = "http://127.0.0.1:8000/api/safety/inspect";
const REQUEST_TIMEOUT_MS = 5000;
const cache = new Map();
const TTL_MS = 30000;
let apiQueue = Promise.resolve();

function postInOrder(url) {
  const request = apiQueue.then(async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      console.info("[Touchless] inspection request:", url, "endpoint:", API);
      const response = await fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`FastAPI returned HTTP ${response.status}`);
      const result = await response.json();
      if (!result || typeof result.allowed !== "boolean" || typeof result.risk !== "string") {
        throw new Error("FastAPI returned a malformed safety decision");
      }
      console.info("[Touchless] FastAPI response:", url, result);
      return result;
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error(`FastAPI inspection timed out after ${REQUEST_TIMEOUT_MS} ms`);
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  });
  // Keep A's serialized ordering so a delayed hover cannot overwrite a newer
  // click target in the FastAPI click gate.
  apiQueue = request.then(() => undefined, () => undefined);
  return request;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "inspect-target") return;
  const url = message.url;
  if (typeof url !== "string" || url.length > 4096) {
    console.warn("[Touchless Protection] Invalid target message", url);
    sendResponse({ url, allowed: null, risk: "unknown", reason: "Unable to inspect target", error: true });
    return;
  }

  if (!url) {
    console.info("[Touchless Protection] Hover left link; clearing FastAPI click target");
    postInOrder(null)
      .then(result => console.info("[Touchless Protection] FastAPI target clear:", result))
      .catch(error => console.warn("[Touchless Protection] Could not clear target:", error.message))
      .finally(() => sendResponse({ url: "", allowed: true, risk: "unknown" }));
    return true;
  }

  const previous = cache.get(url);
  const hasCachedResult = !!previous && Date.now() - previous.time < TTL_MS;
  if (hasCachedResult) {
    console.info("[Touchless Protection] Cached result found; refreshing FastAPI click target:", url);
  } else {
    console.info("[Touchless Protection] POST /api/safety/inspect:", url);
  }

  // Always refresh FastAPI's gate, even when a local result exists. A's cache
  // remains available for freshness tracking, but an inspection failure never
  // turns an old SAFE decision into permission to navigate.
  (async () => {
    try {
      const result = await postInOrder(url);
      cache.set(url, { time: Date.now(), result });
      if (cache.size > 128) {
        for (const [key, value] of cache) {
          if (Date.now() - value.time >= TTL_MS) cache.delete(key);
        }
      }
      sendResponse({ url, ...result });
    } catch (error) {
      console.error("[Touchless Protection] Inspection request failed:", url, error.message,
        hasCachedResult ? "(cached result was not used to allow navigation)" : "");
      // Preserve A's short-lived cached block behavior during outages. A
      // cached SAFE result is deliberately never used to approve navigation.
      if (hasCachedResult && previous.result?.allowed === false) {
        sendResponse({ url, ...previous.result, cached: true, backendUpdated: false, stale: true });
        return;
      }
      sendResponse({
        url,
        allowed: null,
        risk: "unknown",
        reason: error.message || "Unable to inspect target",
        error: true,
        cachedResultAvailable: hasCachedResult,
      });
    }
  })();
  return true;
});
