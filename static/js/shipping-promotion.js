(function () {
  "use strict";
  var configNode = document.getElementById("shipping-promotion-config");
  if (!configNode) return;
  var config = JSON.parse(configNode.textContent);
  var state = config.state;
  var receivedAt = Date.now();
  var timer;
  var pending = false;
  var banner = document.getElementById("shipping-promotion-banner");
  var shippingInfo = document.getElementById("shipping-promotion-info");
  var detail = document.querySelector("[data-promotion-detail-state]");
  var labels = {active: "Promoción vigente", scheduled: "Promoción programada", suspended: "Promoción suspendida", finished: "Promoción finalizada"};

  function render() {
    var now = new Date(state.server_now).getTime() + Date.now() - receivedAt;
    var campaign = state.campaign;
    var visible = campaign && now < new Date(campaign.ends_at).getTime();
    if (banner) {
      banner.hidden = !visible;
      if (visible) {
        banner.querySelector("a").href = campaign.url;
        banner.querySelector("[data-promotion-heading]").textContent = campaign.state === "suspended" ? "Promoción suspendida" : "Envío gratis en CABA";
        banner.querySelector("[data-promotion-copy]").textContent = campaign.state === "suspended" ? "Consultá las condiciones de la campaña." : "Sin mínimo de compra · " + campaign.dates;
      }
    }
    if (detail && state.detail) {
      var detailState = now >= new Date(state.detail.ends_at).getTime() ? "finished" : state.detail.state;
      detail.textContent = labels[detailState] || "Promoción no vigente";
      detail.dataset.promotionDetailState = detailState;
    }
    if (shippingInfo) {
      shippingInfo.hidden = !visible;
      if (visible) {
        shippingInfo.querySelector("a").href = campaign.url;
        shippingInfo.querySelector("[data-promotion-heading]").textContent = campaign.state === "suspended" ? "Promoción de CABA suspendida" : "Promoción: envío gratis en CABA";
        shippingInfo.querySelector("[data-promotion-copy]").textContent = campaign.state === "suspended" ? "Consultá el estado de la campaña y las condiciones habituales de envío." : "Durante la vigencia, las compras con entrega a domicilio en CABA tienen envío gratis, sin mínimo. Moreno y las demás zonas mantienen las condiciones habituales que figuran abajo.";
      }
    }
  }

  function schedule() {
    clearTimeout(timer);
    if (!state.next_change_at) return;
    var serverNow = new Date(state.server_now).getTime() + Date.now() - receivedAt;
    var delay = Math.min(2147483647, Math.max(100, new Date(state.next_change_at).getTime() - serverNow + 100));
    timer = setTimeout(function () { render(); refresh(); }, delay);
  }

  function refresh() {
    if (document.hidden || pending) return;
    pending = true;
    fetch(config.status_url, {cache: "no-store", headers: {"X-Requested-With": "XMLHttpRequest"}})
      .then(function (r) { if (!r.ok) throw new Error("status"); return r.json(); })
      .then(function (data) {
        state = data;
        receivedAt = Date.now();
        render();
        schedule();
        document.dispatchEvent(new CustomEvent("rasel:shipping-promotion-change"));
      })
      .catch(function () { render(); /* Server confirms shipping even offline. */ })
      .finally(function () { pending = false; });
  }
  window.addEventListener("pageshow", refresh);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) { render(); refresh(); } });
  render();
  schedule();
})();
