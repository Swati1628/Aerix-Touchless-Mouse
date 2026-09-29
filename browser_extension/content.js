console.log("[Touchless Protection] content.js LOADED");
(() => {
  const results = new Map();
  const requested = new Set();
  const inspectionWaiters = new Map();
  const RESULT_WARNING_TIMEOUT_MS = 2750;
  let bannerHost = null;
  let banner = null;
  let clickSequence = 0;
  let activeClick = null;
  let lastUrl = null;

  function securityLog(event, details) {
    console.info(`[Touchless SECURITY] ${event}`, details || "");
  }

  function finalAction(action, details) {
    securityLog(`FINAL ACTION: ${action}`, details);
  }

  function linkFor(node) {
    const element = node instanceof Element ? node : node?.parentElement;
    return element?.closest("a[href]") || null;
  }

  function threatIntelligenceFor(result) {
    const nested = result?.threat_intelligence || {};
    return { ...nested, phishtank: nested.phishtank ?? result?.phishtank,
      virustotal: nested.virustotal ?? result?.virustotal };
  }

  function removeWarning() {
    if (!bannerHost) return;
    clearTimeout(bannerHost.hideTimer);
    bannerHost.remove();
    bannerHost = banner = null;
  }

  function showWarning(result, state) {
    removeWarning();
    bannerHost = document.createElement("div");
    bannerHost.setAttribute("aria-live", "assertive");
    bannerHost.style.cssText = "all:initial!important;position:fixed!important;inset:12px 0 auto!important;width:100vw!important;display:flex!important;justify-content:center!important;z-index:2147483647!important;pointer-events:none!important";
    const shadow = bannerHost.attachShadow({ mode: "closed" });
    banner = document.createElement("div");
    banner.setAttribute("role", "alert");
    banner.style.cssText = "all:initial!important;display:block!important;box-sizing:border-box!important;max-width:90vw!important;padding:14px 18px!important;background:#7f1d1d!important;color:#fff!important;border:2px solid #fecaca!important;border-radius:8px!important;font:600 14px/1.45 system-ui,sans-serif!important;white-space:pre-line!important;box-shadow:0 4px 18px #0008!important;pointer-events:auto!important";
    shadow.appendChild(banner);
    (document.documentElement || document.body).appendChild(bannerHost);

    const risk = String(result?.risk || "unknown").toUpperCase();
    if (state === "checking") {
      banner.textContent = "CHECKING LINK SAFETY... Navigation is paused until inspection finishes.";
    } else if (state === "error") {
      banner.textContent = "UNABLE TO INSPECT LINK. Navigation was blocked because its safety could not be verified.";
    } else if (risk === "suspicious") {
      banner.textContent = `SUSPICIOUS LINK: ${result.reason || "The destination needs your review."} Navigation is paused.`;
      addContinueButton(shadow, activeClick);
    } else {
      const intel = threatIntelligenceFor(result);
      const sources = [];
      if (intel.phishtank?.matched) sources.push("PhishTank");
      if (Number(intel.virustotal?.malicious || 0) > 0) sources.push("VirusTotal");
      if (result.ai_detected) sources.push("local ML");
      banner.textContent = `${risk} LINK BLOCKED: ${result.reason || "Potentially dangerous URL"}. ${sources.length ? `Source: ${sources.join(", ")}. ` : ""}Navigation blocked.`;
    }
    const warningHost = bannerHost;
    const warningClickId = activeClick?.id;
    bannerHost.hideTimer = setTimeout(() => {
      if (bannerHost !== warningHost) return;
      // A dismissed warning must not leave an intercepted click or a reserved
      // about:blank tab stuck indefinitely.
      if (state !== "checking" && warningClickId && activeClick?.id === warningClickId) {
        const expiredClick = activeClick;
        activeClick = null;
        try { expiredClick.popup?.close(); } catch (_) { /* tab may already be closed */ }
      }
      removeWarning();
    }, state === "checking" ? 30000 : RESULT_WARNING_TIMEOUT_MS);
  }

  function addContinueButton(shadow, pending) {
    if (!pending) return;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Continue anyway";
    button.style.cssText = "margin-top:10px;padding:7px 12px;border:1px solid white;border-radius:4px;background:#fff;color:#7f1d1d;font:600 14px system-ui;cursor:pointer";
    button.addEventListener("click", () => {
      if (activeClick?.id !== pending.id || activeClick.continued) return;
      console.info("[Touchless] continue clicked:", activeClick.url, "target:", activeClick.target, "request:", activeClick.id);
      activeClick.continued = true;
      const destination = activeClick;
      activeClick = null;
      removeWarning();
      finalAction("ALLOW", { url: destination.url, requestId: destination.id,
        reason: "user chose Continue Anyway" });
      continueNavigation(destination);
    });
    shadow.appendChild(button);
  }

  function continueNavigation(pending) {
    console.info("[Touchless] original URL:", pending.url, "target:", pending.target, "request:", pending.id);
    console.info("[Touchless] navigating to:", pending.url);
    if (pending.popup) {
      try {
        pending.popup.location.href = pending.url;
      } catch (error) {
        console.error("[Touchless] Reserved tab navigation failed; using new-tab fallback:", error);
        window.open(pending.url, pending.target || "_blank");
      }
      return;
    }
    if (pending.target && pending.target !== "_self") {
      window.open(pending.url, pending.target, pending.features);
      return;
    }
    window.location.assign(pending.url);
  }

  function requestInspection(url, callback, refreshBackendTarget = false) {
    if (requested.has(url)) {
      if (refreshBackendTarget) {
        // A click must wait for its own fresh decision. Never let an in-flight
        // hover inspection's older result release this navigation.
        chrome.runtime.sendMessage({ type: "inspect-target", url }, response => {
          const outcome = inspectionOutcome(url, response);
          if (!outcome.error) results.set(url, outcome);
          console.info("[Touchless] inspection result:", url, outcome);
          if (callback) callback(outcome);
        });
      } else if (callback) {
        const waiters = inspectionWaiters.get(url);
        if (waiters) waiters.push(callback);
        else callback({ error: "Inspection is no longer available." });
      }
      return;
    }
    requested.add(url);
    inspectionWaiters.set(url, callback ? [callback] : []);
    console.info("[Touchless] inspection request:", url);
    chrome.runtime.sendMessage({ type: "inspect-target", url }, response => {
      requested.delete(url);
      const waiters = inspectionWaiters.get(url) || [];
      inspectionWaiters.delete(url);
      const outcome = inspectionOutcome(url, response);
      if (!outcome.error) {
        results.set(url, outcome);
      }
      console.info("[Touchless] inspection result:", url, outcome);
      // Render an unsafe result once before dispatching click/hover consumers.
      // Mousemove can otherwise queue many identical hover callbacks while a
      // request is pending, causing each callback to rebuild the same popup.
      if (!outcome.error && outcome.allowed === false &&
          (!activeClick || activeClick.url === url)) {
        showWarning(outcome, "result");
      }
      waiters.forEach(waiter => waiter(outcome));
    });
  }

  function inspectionOutcome(url, response) {
    if (chrome.runtime.lastError) {
      return { error: chrome.runtime.lastError.message || "Inspection request failed." };
    }
    if (!response || response.url !== url || typeof response.allowed !== "boolean" ||
        typeof response.risk !== "string") {
      return { error: response?.reason || "No valid safety decision was returned." };
    }
    return { ...response, time: Date.now() };
  }

  function inspect(url) {
    const target = url || "";
    if (target === lastUrl) return;
    lastUrl = target;
    if (!target) {
      // Preserve A's hover-leave notification so the FastAPI mouse click gate
      // does not keep treating a link that is no longer under the pointer as
      // the current target.
      chrome.runtime.sendMessage({ type: "inspect-target", url: "" }, () => {
        if (chrome.runtime.lastError) {
          console.warn("[Touchless Protection] Target clear message failed:", chrome.runtime.lastError.message);
        }
      });
      return;
    }
    const cached = results.get(url);
    if (cached && Date.now() - cached.time < 30000) {
      if (!cached.allowed) showWarning(cached, "result");
    }
    // Refresh the backend target even when the content cache has a fresh
    // result. This keeps the existing mouse/software click integration in sync.
    requestInspection(target, null, true);
  }

  document.addEventListener("mouseover", event => inspect(linkFor(event.target)?.href), { passive: true, capture: true });
  document.addEventListener("mousemove", event => inspect(linkFor(event.target)?.href), { passive: true, capture: true });

  function interceptClick(event) {
    // Preserve browser handling for context menus, middle click, and modifier clicks.
    if (event.type !== "click" || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const anchor = linkFor(event.target);
    if (!anchor || anchor.hasAttribute("download") || !["http:", "https:"].includes(new URL(anchor.href).protocol)) return;
    const url = anchor.href;
    console.info("[Touchless DEBUG] clicked href:", anchor.getAttribute("href"));
    console.info("[Touchless DEBUG] resolved URL:", url);
    console.info("[Touchless] clicked URL:", url);
    console.info("[Touchless DEBUG] current page URL:", window.location.href);
    console.info("[Touchless DEBUG] link text:", (anchor.innerText || anchor.getAttribute("aria-label") || "").trim());
    console.info("[Touchless DEBUG] target:", anchor.target || "_self");
    event.preventDefault();
    event.stopImmediatePropagation();
    const id = ++clickSequence;
    securityLog("CLICK INTERCEPTED", { url, requestId: id });
    if (activeClick) {
      const staleClick = activeClick;
      activeClick = null;
      try { staleClick.popup?.close(); } catch (_) { /* tab may already be closed */ }
      removeWarning();
      console.warn("[Touchless] Ignoring a second link click while inspection is pending:",
        url, "invalidated request:", staleClick.id, staleClick.url);
      finalAction("BLOCK", { url, requestId: id, reason: "another inspection was already pending" });
      return;
    }

    // Reserve a tab during the user gesture so a safe _blank link can resume later.
    const target = anchor.target || "_self";
    const popup = target !== "_self" ? window.open("about:blank", target) : null;
    if (popup) popup.opener = null;
    activeClick = { id, url, target, popup, features: "noopener", continued: false };
    showWarning({}, "checking");
    securityLog("INSPECTION STARTED", { url, requestId: id });
    requestInspection(url, result => {
      const intel = threatIntelligenceFor(result);
      const risk = String(result.risk || "unknown").toLowerCase();
      securityLog("INSPECTION RESULT", {
        url,
        requestId: id,
        risk,
        allowed: result.allowed,
        virustotal: intel.virustotal?.status || "not_checked",
        phishtank: intel.phishtank?.status || "not_checked",
      });
      if (activeClick?.id !== id) {
        finalAction("BLOCK", { url, requestId: id, reason: "stale inspection result ignored" });
        return;
      }
      if (result.error) {
        const blockedNavigation = activeClick;
        activeClick = null;
        try { blockedNavigation.popup?.close(); } catch (_) { /* tab may already be closed */ }
        showWarning(result, "error");
        finalAction("ERROR_BLOCK", { url, requestId: id, reason: result.error });
      } else if (result.allowed === true && risk === "safe") {
        const navigation = activeClick;
        activeClick = null;
        removeWarning();
        finalAction("ALLOW", { url, requestId: id, risk });
        continueNavigation(navigation);
      } else if (risk === "suspicious") {
        showWarning(result, "result");
        finalAction("WARN", { url, requestId: id, risk });
      } else {
        // Dangerous, parental-blocked, contradictory, and unknown results
        // never release the original navigation.
        const blockedNavigation = activeClick;
        activeClick = null;
        try { blockedNavigation.popup?.close(); } catch (_) { /* tab may already be closed */ }
        if (risk === "dangerous" || risk === "blocked") {
          showWarning(result, "result");
          finalAction("BLOCK", { url, requestId: id, risk });
        } else {
          showWarning({ reason: "No valid SAFE decision was returned." }, "error");
          finalAction("ERROR_BLOCK", { url, requestId: id, risk, allowed: result.allowed });
        }
      }
    }, true);
  }

  document.addEventListener("click", interceptClick, true);
})();
