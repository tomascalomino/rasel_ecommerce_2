(function () {
  var cpInput = document.getElementById("id_postal_code");
  var summary = document.querySelector(".ship-summary");
  if (!cpInput || !summary) return;

  var confirmEl = document.getElementById("ship-confirm");
  var sumSubtotal = document.getElementById("sum-subtotal");
  var sumShipping = document.getElementById("sum-shipping");
  var discountRow = document.getElementById("payment-discount-row");
  var sumDiscount = document.getElementById("sum-payment-discount");
  var sumTotal = document.getElementById("sum-total");
  var sumTotalLabel = document.getElementById("sum-total-label");
  var quoteUrl = summary.getAttribute("data-quote-url");
  var shopUrl = summary.getAttribute("data-shop-url");
  var subtotal = parseFloat(summary.getAttribute("data-subtotal")) || 0;
  var offlineDiscount = parseFloat(summary.getAttribute("data-offline-discount")) || 0;
  var discountPercent = summary.getAttribute("data-discount-percent") || "0";
  var discountEnabled = offlineDiscount > 0 && parseFloat(discountPercent) > 0;
  var currentShippingCost = 0;
  var shippingKnown = false;
  var quoteToken = document.getElementById("id_shipping_quote_token");
  var quoteVersion = 0;
  var timer;

  var codRadio = document.querySelector('input[name="payment_method"][value="cod"]');
  var paymentRadios = document.querySelectorAll('input[name="payment_method"]');
  var codHint = document.getElementById("cod-hint");
  var COD_HINT_DEFAULT = discountEnabled
    ? discountPercent + "% de descuento. Disponible para retiro o entrega en persona en CABA y GBA."
    : "Disponible para retiro o entrega en persona en CABA y GBA.";

  function codPaymentMessage(moment) {
    var message = "Pagás en efectivo al " + moment + ".";
    return discountEnabled
      ? message.slice(0, -1) + " con " + discountPercent + "% de descuento."
      : message;
  }

  var deliveryRadios = document.querySelectorAll('input[name="delivery_method"]');
  var shipFields = document.getElementById("ship-fields");
  var pickupFields = document.getElementById("pickup-fields");

  function deliveryMode() {
    var checked = document.querySelector('input[name="delivery_method"]:checked');
    return checked ? checked.value : "ship";
  }

  function money(n) {
    var rounded = Math.round((n + Number.EPSILON) * 100) / 100;
    return "$ " + new Intl.NumberFormat("es-AR", {
      minimumFractionDigits: Number.isInteger(rounded) ? 0 : 2,
      maximumFractionDigits: 2
    }).format(rounded);
  }

  function selectedPaymentMethod() {
    var checked = document.querySelector('input[name="payment_method"]:checked');
    return checked ? checked.value : "transfer";
  }

  function refreshTotals() {
    var method = selectedPaymentMethod();
    var hasDiscount = discountEnabled && (method === "transfer" || method === "cod");
    var discount = hasDiscount ? offlineDiscount : 0;
    discountRow.hidden = !hasDiscount;
    sumDiscount.textContent = "− " + money(discount);
    sumTotalLabel.textContent = !shippingKnown ? "Total estimado" : hasDiscount
      ? "Total con precio especial"
      : "Total";
    sumTotal.textContent = money(subtotal - discount + currentShippingCost);
    var submitTotal = document.getElementById("submit-total");
    var submitLabel = document.getElementById("submit-total-label");
    var submitShipping = document.getElementById("submit-shipping");
    if (submitTotal) submitTotal.textContent = sumTotal.textContent;
    if (submitLabel) submitLabel.textContent = sumTotalLabel.textContent;
    if (submitShipping) submitShipping.textContent = shippingKnown ? sumShipping.textContent : "A confirmar con tu CP";
  }

  // Habilita/deshabilita contraentrega según la zona del CP. Si estaba
  // seleccionada y deja de estar disponible, cae al primer método habilitado.
  // El servidor re-valida igual en el POST.
  function setCod(enabled, msg) {
    if (!codRadio) return;
    codRadio.disabled = !enabled;
    var label = codRadio.closest("label");
    if (label) label.classList.toggle("is-disabled", !enabled);
    if (!enabled && codRadio.checked) {
      codRadio.checked = false;
      var fallback = document.querySelector('input[name="payment_method"]:not([disabled])');
      if (fallback) fallback.checked = true;
      msg = "Contraentrega no disponible para tu código postal. Cambiamos el método de pago.";
    }
    if (codHint) codHint.textContent = msg || COD_HINT_DEFAULT;
  }

  // Alterna entre envío a domicilio (cotización por CP) y retiro sin cargo.
  function applyDelivery(mode) {
    if (mode === "pickup") {
      quoteVersion++;
      quoteToken.value = "";
      shippingKnown = true;
      shipFields.hidden = true;
      pickupFields.hidden = false;
      confirmEl.hidden = true;
      sumShipping.textContent = "Retiro sin cargo";
      sumShipping.className = "ship-free";
      currentShippingCost = 0;
      setCod(true, codPaymentMessage("retirar"));
      refreshTotals();
    } else {
      shipFields.hidden = false;
      pickupFields.hidden = true;
      reset();
      if (cpInput.value.trim().replace(/\D/g, "").length >= 4) fetchQuote();
    }
  }

  deliveryRadios.forEach(function (radio) {
    radio.addEventListener("change", function () {
      applyDelivery(deliveryMode());
    });
  });

  paymentRadios.forEach(function (radio) {
    radio.addEventListener("change", refreshTotals);
  });

  // Subtotal con formato consistente desde el primer render.
  sumSubtotal.textContent = money(subtotal);

  function reset(msg) {
    quoteToken.value = "";
    shippingKnown = false;
    confirmEl.hidden = true;
    confirmEl.className = "ship-confirm";
    sumShipping.textContent = msg || "Ingresá tu CP";
    sumShipping.className = "muted";
    currentShippingCost = 0;
    setCod(false, COD_HINT_DEFAULT);
    refreshTotals();
  }

  function render(data) {
    // Una respuesta en vuelo no debe pisar el resumen en modo retiro.
    if (deliveryMode() === "pickup") return;
    if (!data || !data.ok) {
      reset();
      return;
    }
    var cost = parseFloat(data.cost) || 0;
    var loc = data.location_label || ("CP " + data.cp);
    quoteToken.value = data.quote_token || "";
    shippingKnown = true;
    confirmEl.replaceChildren();
    function textLine(value, className) {
      var line = document.createElement("div");
      if (className) line.className = className;
      line.textContent = value;
      confirmEl.appendChild(line);
      return line;
    }

    // Envío a cargo del comprador (resto del país): costo 0 pero no es "gratis".
    if (data.carrier_arranged) {
      setCod(false, "No disponible para envíos por correo (resto del país).");
      confirmEl.hidden = false;
      confirmEl.className = "ship-confirm";
      textLine(loc + " — Envío a coordinar");
      textLine(data.note || "", "ship-legend");
      sumShipping.textContent = "A coordinar";
      sumShipping.className = "muted";
      currentShippingCost = 0;
      refreshTotals();
      return;
    }

    setCod(
      !!data.cod_allowed,
      data.cod_allowed
        ? codPaymentMessage("recibir")
        : "No disponible para tu zona."
    );

    var label = data.free ? "Envío gratis" : money(cost);

    // Nudge: cuánto falta para alcanzar el envío gratis en esta zona.
    var remaining = parseFloat(data.remaining_for_free);
    confirmEl.hidden = false;
    confirmEl.className = "ship-confirm" + (data.free ? " is-free" : "");
    textLine(loc + " — " + label);
    textLine(data.promotion ? "Promoción exclusiva para CABA" : data.zone_name, "muted tiny");
    if (data.promotion) {
      var campaignLine = textLine("Envío gratis por la promoción de CABA. ", "ship-legend");
      var conditions = document.createElement("a");
      conditions.href = data.promotion.url;
      conditions.textContent = "Ver condiciones";
      conditions.className = "promotion-text-link";
      campaignLine.appendChild(conditions);
    }
    if (!data.free && remaining > 0) {
      var nudge = textLine("Agregá " + money(remaining) + " para envío gratis", "ship-nudge");
      var more = document.createElement("a");
      more.href = shopUrl;
      more.className = "ship-nudge-link";
      more.textContent = "Agregar más productos →";
      nudge.appendChild(more);
    }

    sumShipping.textContent = data.promotion ? "Gratis · promoción CABA" : data.free ? "Gratis" : money(cost);
    sumShipping.className = data.free ? "ship-free" : "";
    currentShippingCost = cost;
    refreshTotals();
  }

  function fetchQuote() {
    if (deliveryMode() === "pickup") return;
    var cp = cpInput.value.trim();
    var version = ++quoteVersion;
    quoteToken.value = "";
    if (cp.replace(/\D/g, "").length < 4) {
      reset();
      return;
    }
    fetch(
      quoteUrl + "?postal_code=" + encodeURIComponent(cp) +
        "&subtotal=" + encodeURIComponent(subtotal),
      { cache: "no-store", headers: { "X-Requested-With": "XMLHttpRequest" } }
    )
      .then(function (r) { if (!r.ok) throw new Error("quote"); return r.json(); })
      .then(function (data) {
        if (version === quoteVersion && cp === cpInput.value.trim() && deliveryMode() === "ship") render(data);
      })
      .catch(function () { if (version === quoteVersion && deliveryMode() === "ship") reset("Revisamos el envío al confirmar"); });
  }

  cpInput.addEventListener("input", function () {
    quoteVersion++;
    reset();
    clearTimeout(timer);
    timer = setTimeout(fetchQuote, 400);
  });

  // Persistencia liviana del form (sessionStorage): el link "Agregar más
  // productos" del nudge saca al cliente del checkout; al volver, los campos
  // se restauran para no castigarlo con re-tipeo. Solo se llenan campos
  // vacíos (un POST con errores re-renderiza valores del server y esos ganan).
  // try/catch silencioso: la persistencia nunca rompe el checkout.
  var PERSIST_KEY = "rasel_checkout_form";
  var PERSIST_FIELDS = [
    "full_name", "email", "phone",
    "address_line", "address_extra", "city", "postal_code"
  ];
  try {
    var saved = JSON.parse(sessionStorage.getItem(PERSIST_KEY) || "{}");
    PERSIST_FIELDS.forEach(function (name) {
      var input = document.getElementById("id_" + name);
      if (!input) return;
      if (!input.value && saved[name]) input.value = saved[name];
      input.addEventListener("input", function () {
        try {
          var data = JSON.parse(sessionStorage.getItem(PERSIST_KEY) || "{}");
          data[name] = input.value;
          sessionStorage.setItem(PERSIST_KEY, JSON.stringify(data));
        } catch (e) { /* silencioso */ }
      });
    });
  } catch (e) { /* silencioso */ }

  // Estado inicial según el radio marcado (importa en re-renders con errores):
  // en envío re-cotiza si el CP ya viene cargado; en retiro aplica el modo.
  // Corre después de la restauración para que un CP restaurado re-cotice solo.
  applyDelivery(deliveryMode());
  document.addEventListener("rasel:shipping-promotion-change", fetchQuote);
})();
