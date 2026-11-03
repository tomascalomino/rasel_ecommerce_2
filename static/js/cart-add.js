(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var dialog = document.getElementById("cart-added-dialog");
    if (!dialog || typeof dialog.showModal !== "function" || !window.fetch) return;
    var content = dialog.querySelector("[data-cart-added-content]");
    var returnFocus;
    var pending = false;

    function close() {
      dialog.close();
    }

    dialog.querySelector("[data-cart-added-close]").addEventListener("click", close);
    dialog.addEventListener("click", function (event) {
      if (event.target.closest("[data-cart-added-continue]")) {
        event.preventDefault();
        close();
      } else if (event.target === dialog) {
        var box = dialog.getBoundingClientRect();
        if (event.clientX < box.left || event.clientX > box.right ||
            event.clientY < box.top || event.clientY > box.bottom) close();
      }
    });
    dialog.addEventListener("close", function () {
      document.documentElement.classList.remove("cart-confirmation-open");
      if (returnFocus && returnFocus.isConnected) returnFocus.focus({preventScroll: true});
    });
    window.addEventListener("pageshow", function (event) {
      if (event.persisted && dialog.open) close();
    });

    document.querySelectorAll("[data-cart-add-form]").forEach(function (form) {
      form.addEventListener("submit", async function (event) {
        event.preventDefault();
        if (pending) return;
        pending = true;
        var submit = form.querySelector('button[type="submit"]');
        var label = submit.innerHTML;
        var error = form.querySelector("[data-cart-add-error]");
        var sourceDialog = form.closest("dialog");
        var controller = new AbortController();
        var timeout = setTimeout(function () { controller.abort(); }, 20000);
        error.hidden = true;
        form.setAttribute("aria-busy", "true");
        submit.disabled = true;
        submit.textContent = "Agregando…";
        try {
          var response = await fetch(form.action, {
            method: "POST",
            credentials: "same-origin",
            signal: controller.signal,
            headers: {"Accept": "application/json"},
            body: new FormData(form)
          });
          var result = await response.json();
          if (!response.ok) {
            error.textContent = result.error || "No se pudo agregar el producto. Volvé a intentarlo.";
            error.hidden = false;
            return;
          }
          content.innerHTML = result.html;
          document.querySelectorAll('.pill-cart .badge-num').forEach(function (badge) {
            badge.textContent = result.cart_quantity;
          });
          returnFocus = sourceDialog ? sourceDialog.quickAddOpener : submit;
          if (sourceDialog) sourceDialog.close();
          document.documentElement.classList.add("cart-confirmation-open");
          dialog.showModal();
          content.querySelector("[data-cart-added-checkout]").focus({preventScroll: true});
          document.dispatchEvent(new CustomEvent("rasel:cart-added", {detail: {events: result.meta_events || []}}));
        } catch (failure) {
          // A lost response may follow a successful POST. Never resubmit automatically.
          error.textContent = "No pudimos confirmar si se agregó. ";
          var link = document.createElement("a");
          link.href = content.querySelector('.cart-added-review')?.href || document.querySelector('.pill-cart').href;
          link.textContent = "Revisá tu carrito antes de volver a agregar.";
          error.appendChild(link);
          error.hidden = false;
        } finally {
          clearTimeout(timeout);
          pending = false;
          form.removeAttribute("aria-busy");
          submit.disabled = false;
          submit.innerHTML = label;
        }
      });
    });
  });
})();
