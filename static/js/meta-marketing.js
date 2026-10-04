(function () {
  "use strict";
  var configElement = document.getElementById("rasel-meta-config");
  if (!configElement) return;
  if (window.raselMetaMarketingLoaded) return;
  window.raselMetaMarketingLoaded = true;
  var config = JSON.parse(configElement.textContent);
  var banner = document.querySelector("[data-meta-banner]");
  var status = document.querySelector("[data-meta-status]");
  var close = document.querySelector("[data-meta-close]");
  var state = config.state;
  var pageTracked = false;
  var claimsRunning = false;
  var generation = 0;
  var synchronization = 0;

  function removeCookies() {
    ["_fbp", "_fbc"].forEach(function (name) {
      var parts = window.location.hostname.split(".");
      document.cookie = name + "=; Max-Age=0; path=/; SameSite=Lax";
      for (var i = 0; i < parts.length - 1; i++) {
        var domain = parts.slice(i).join(".");
        document.cookie = name + "=; Max-Age=0; path=/; domain=" + domain + "; SameSite=Lax";
        document.cookie = name + "=; Max-Age=0; path=/; domain=." + domain + "; SameSite=Lax";
      }
    });
  }

  function installPixel() {
    // Official bootstrap from the supplied Meta Pixel Code; only after consent.
    !function(f,b,e,v,n,t,s)
    {if(f.fbq)return;n=f.fbq=function(){n.callMethod?
    n.callMethod.apply(n,arguments):n.queue.push(arguments)};
    if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
    n.queue=[];t=b.createElement(e);t.async=!0;
    t.src=v;s=b.getElementsByTagName(e)[0];
    s.parentNode.insertBefore(t,s)}(window, document,'script',
    'https://connect.facebook.net/en_US/fbevents.js');
    if (!window.raselMetaPixelInitialized) {
      window.fbq("set", "autoConfig", false, config.pixelId);
      window.fbq("consent", "grant");
      window.fbq("init", config.pixelId);
      window.raselMetaPixelInitialized = true;
    } else {
      window.fbq("consent", "grant");
    }
  }

  function track(name, data, id) {
    if (state !== "accepted" || !config.pixelEnabled) return;
    window.fbq("trackSingle", config.pixelId, name, data || {}, id ? {eventID: id} : {});
  }

  function claimEvents() {
    if (claimsRunning || state !== "accepted" || !config.pixelEnabled) return;
    claimsRunning = true;
    var currentGeneration = generation;
    Promise.all(config.events.map(function (event) {
      return fetch(config.claimEndpoint, {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRFToken": config.csrf},
        body: JSON.stringify({token: event.token})
      }).then(function (response) { return response.ok ? response.json() : null; })
        .then(function (result) {
          if (result && result.claimed && currentGeneration === generation && state === "accepted") {
            track(result.name, result.data, result.id);
          }
        }).catch(function () {});
    })).finally(function () { claimsRunning = false; });
  }

  function activate() {
    if (state !== "accepted" || !config.pixelEnabled) return;
    installPixel();
    if (!pageTracked) {
      pageTracked = true;
      track("PageView");
      if (config.product) {
        var select = document.getElementById("product-variant");
        var option = select && select.options[select.selectedIndex];
        if (option && !option.disabled && option.value) {
          track("ViewContent", {
            content_type: "product", content_ids: [option.value],
            contents: [{id: option.value, quantity: 1}],
            currency: "ARS", value: Number(option.dataset.price)
          });
        } else {
          track("ViewContent");
        }
      }
    }
    claimEvents();
  }

  function applyState(next) {
    if (state !== next) generation++;
    state = next;
    if (state === "unknown") banner.hidden = false;
    close.hidden = state === "unknown";
    if (state !== "accepted") {
      if (window.fbq) {
        if (!window.fbq.callMethod && window.fbq.queue) {
          // Withdraw even events buffered while the asynchronous SDK is loading.
          window.fbq.queue = [];
          window.raselMetaPixelInitialized = false;
        }
        window.fbq("consent", "revoke");
      }
      removeCookies();
    } else {
      activate();
    }
  }

  function synchronize() {
    var requestVersion = ++synchronization;
    return fetch(config.consentEndpoint, {credentials: "same-origin", cache: "no-store"})
      .then(function (response) { if (!response.ok) throw new Error("consent"); return response.json(); })
      .then(function (result) { if (requestVersion === synchronization) applyState(result.state); })
      .catch(function () { if (requestVersion === synchronization) applyState("unknown"); });
  }

  document.querySelectorAll("[data-meta-choice]").forEach(function (button) {
    button.addEventListener("click", function () {
      status.textContent = "Guardando tu elección…";
      ++synchronization;
      var buttons = document.querySelectorAll("[data-meta-choice]");
      buttons.forEach(function (item) { item.disabled = true; });
      fetch(config.consentEndpoint, {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRFToken": config.csrf},
        body: JSON.stringify({accepted: button.dataset.metaChoice === "accept", pageToken: config.pageToken})
      }).then(function (response) {
        if (!response.ok) throw new Error("consent");
        return response.json();
      }).then(function (result) {
        applyState(result.state);
        try { window.localStorage.setItem("rasel-meta-choice-change", String(Date.now()) + Math.random()); } catch (error) {}
        banner.hidden = true;
        status.textContent = "";
      }).catch(function () {
        status.textContent = "No pudimos guardar tu elección. Podés seguir comprando y reintentarlo.";
      }).finally(function () { buttons.forEach(function (item) { item.disabled = false; }); });
    });
  });
  document.querySelectorAll("[data-meta-preferences]").forEach(function (button) {
    button.addEventListener("click", function () {
      banner.hidden = false;
      close.hidden = state === "unknown";
      var header = document.querySelector(".topbar");
      banner.style.scrollMarginTop = ((header ? header.getBoundingClientRect().height : 0) + 8) + "px";
      banner.scrollIntoView({behavior: "smooth", block: "nearest"});
      banner.querySelector("[data-meta-choice]").focus({preventScroll: true});
    });
  });
  close.addEventListener("click", function () { banner.hidden = true; });
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) pageTracked = false;
    synchronize();
  });
  window.addEventListener("focus", synchronize);
  window.addEventListener("storage", function (event) {
    if (event.key === "rasel-meta-choice-change") {
      applyState("unknown");
      synchronize();
    }
  });
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") synchronize();
  });
  // Verify current server choice before emitting from cached HTML or another tab.
  synchronize();
})();
