(() => {
  const host = new URLSearchParams(window.location.search).get("host") || "Unknown";
  document.getElementById("blocked-host").textContent = host;
  console.warn(`[Aerix] HARD BLOCK: hostname=${host}`);
  console.warn("[Aerix] Navigation blocked by custom security policy");
})();
