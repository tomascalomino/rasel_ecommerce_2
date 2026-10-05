(function () {
  "use strict";

  var media = document.querySelector("[data-hero-mobile-media]");
  if (!media) return;

  var video = media.querySelector("video");
  var toggle = media.querySelector("button");
  var actions = media.closest(".hero-full").querySelector(".cta-row");
  var floatingContact = document.querySelector(".wa-float");
  var mobile = window.matchMedia("(max-width: 768px)");
  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  var connection = navigator.connection;
  var visible = false;
  var actionsVisible = false;
  var userPaused = false;
  var failed = false;
  var revision = 0;

  function allowed() {
    return mobile.matches && !reducedMotion.matches && !(connection && connection.saveData);
  }

  function updateToggle() {
    toggle.hidden = !allowed() || failed || !video.hasAttribute("src");
    toggle.textContent = video.paused ? "Reanudar video" : "Pausar video";
    toggle.setAttribute("aria-label", toggle.textContent);
  }

  function sync() {
    if (floatingContact) {
      floatingContact.classList.toggle("hero-actions-visible", mobile.matches && actionsVisible);
    }
    var currentRevision = ++revision;
    if (!allowed()) {
      video.pause();
      media.classList.remove("is-playing");
      if (video.hasAttribute("src")) {
        video.removeAttribute("src");
        video.load();
      }
      failed = false;
      updateToggle();
      return;
    }

    if (!visible || document.hidden || userPaused || failed) {
      video.pause();
      updateToggle();
      return;
    }

    if (!video.hasAttribute("src")) {
      video.muted = true;
      video.src = video.dataset.src;
      video.load();
    }
    var play = video.play();
    if (play && play.catch) {
      play.catch(function () {
        if (currentRevision !== revision) return;
        userPaused = true;
        media.classList.remove("is-playing");
        updateToggle();
      });
    }
    updateToggle();
  }

  toggle.addEventListener("click", function () {
    userPaused = !video.paused;
    sync();
  });
  video.addEventListener("playing", function () {
    if (!allowed() || !visible || document.hidden || userPaused) {
      video.pause();
      return;
    }
    media.classList.add("is-playing");
    updateToggle();
  });
  video.addEventListener("pause", updateToggle);
  video.addEventListener("error", function () {
    if (!video.hasAttribute("src")) return;
    failed = true;
    media.classList.remove("is-playing");
    updateToggle();
  });

  mobile.addEventListener("change", sync);
  reducedMotion.addEventListener("change", sync);
  if (connection && connection.addEventListener) connection.addEventListener("change", sync);
  document.addEventListener("visibilitychange", sync);
  window.addEventListener("pageshow", sync);
  window.addEventListener("pagehide", function () {
    ++revision;
    video.pause();
  });

  if ("IntersectionObserver" in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.target === media) visible = entry.isIntersecting;
        if (entry.target === actions) actionsVisible = entry.isIntersecting;
      });
      sync();
    });
    observer.observe(media);
    if (actions) observer.observe(actions);
  }
  // Without visibility observation, keep the still frame and avoid background playback.
  sync();
}());
