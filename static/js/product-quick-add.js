(function () {
  "use strict";

  function money(value) {
    return "$ " + new Intl.NumberFormat("es-AR", {
      minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
      maximumFractionDigits: 2
    }).format(value);
  }

  function refreshVariant(dialog) {
    var select = dialog.querySelector("[data-quick-add-variant]");
    if (!select) return;

    var option = select.options[select.selectedIndex];
    if (!option) return;

    var currentPrice = dialog.querySelector("[data-quick-add-current-price]");
    var promotionComparison = dialog.querySelector("[data-quick-add-promotion-comparison]");
    var promotionLabel = dialog.querySelector("[data-quick-add-promotion-label]");
    var compareAtPrice = dialog.querySelector("[data-quick-add-compare-at-price]");
    var offlinePrice = dialog.querySelector("[data-quick-add-offline-price]");
    var quantity = dialog.querySelector("[data-quick-add-qty-input]");
    var stock = parseInt(option.dataset.stock, 10) || 1;
    var currentValue = parseFloat(option.dataset.price) || 0;
    var compareValue = parseFloat(option.dataset.compareAtPrice);
    var label = (option.dataset.promotionLabel || "").trim();
    var hasComparison = Number.isFinite(compareValue) && compareValue > currentValue && Boolean(label);

    currentPrice.textContent = money(currentValue);
    promotionComparison.hidden = !hasComparison;
    if (hasComparison) {
      promotionLabel.textContent = label;
      compareAtPrice.textContent = money(compareValue);
      compareAtPrice.setAttribute("aria-label", "Precio regular " + money(compareValue));
    }
    offlinePrice.textContent = money(parseFloat(option.dataset.offlinePrice) || 0);
    quantity.max = stock;
    if ((parseInt(quantity.value, 10) || 1) > stock) quantity.value = stock;
  }

  function changeQuantity(dialog, direction) {
    var input = dialog.querySelector("[data-quick-add-qty-input]");
    var current = parseInt(input.value, 10) || 1;
    var maximum = parseInt(input.max, 10) || current + 1;

    if (direction === "increase") {
      input.value = Math.min(current + 1, maximum);
    } else {
      input.value = Math.max(current - 1, 1);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-quick-add-dialog]").forEach(function (dialog) {
      var select = dialog.querySelector("[data-quick-add-variant]");
      if (select) {
        select.addEventListener("change", function () {
          refreshVariant(dialog);
        });
        refreshVariant(dialog);
      }

      dialog.querySelectorAll("[data-quick-add-close]").forEach(function (button) {
        button.addEventListener("click", function () {
          dialog.close();
        });
      });

      dialog.querySelectorAll("[data-quick-add-qty]").forEach(function (button) {
        button.addEventListener("click", function () {
          changeQuantity(dialog, button.dataset.quickAddQty);
        });
      });

      dialog.addEventListener("click", function (event) {
        if (event.target === dialog) dialog.close();
      });
    });

    document.querySelectorAll("[data-quick-add-open]").forEach(function (opener) {
      opener.addEventListener("click", function (event) {
        var dialog = document.getElementById(opener.dataset.quickAddOpen);
        if (!dialog || typeof dialog.showModal !== "function") return;
        event.preventDefault();
        dialog.showModal();
      });
    });
  });
})();
