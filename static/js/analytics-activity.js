/* One first-party signal per page. Never read form values or send URLs. */
(function () {
  "use strict";
  var config = document.querySelector("meta[name='rasel-activity']");
  if (!config || !window.fetch) return;
  var sent = false;
  var visibleMs = 0;
  var visibleSince = null;
  var timer;
  function send(event) {
    if (sent || document.visibilityState !== "visible" || document.prerendering) return;
    sent = true;
    clearTimeout(timer);
    fetch(config.dataset.endpoint, {
      method: "POST", credentials: "same-origin", keepalive: true,
      headers: { "Content-Type": "application/json", "X-CSRFToken": config.dataset.csrf },
      body: JSON.stringify({event: event, token: config.content})
    }).catch(function () {});
  }
  function visibility() {
    clearTimeout(timer);
    if (visibleSince !== null) visibleMs += performance.now() - visibleSince;
    visibleSince = null;
    if (!sent && document.visibilityState === "visible" && !document.prerendering) {
      visibleSince = performance.now();
      timer = setTimeout(function () { send("visible"); }, Math.max(0, 10500 - visibleMs));
    }
  }
  ["pointerdown", "click", "keydown", "touchstart", "wheel"].forEach(function (name) {
    document.addEventListener(name, function (event) {
      if (event.isTrusted) send("interaction");
    }, {passive: true});
  });
  document.addEventListener("visibilitychange", visibility);
  document.addEventListener("prerenderingchange", visibility);
  window.addEventListener("pagehide", function () {
    clearTimeout(timer);
    if (visibleSince !== null) visibleMs += performance.now() - visibleSince;
    visibleSince = null;
  });
  window.addEventListener("pageshow", visibility);
  visibility();
}());
