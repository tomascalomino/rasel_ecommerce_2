from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from cart.cart import Cart
from config.pricing import get_offline_payment_discount_percent
from .coupons import SESSION_KEY, normalize_code, quote_coupon


@never_cache
@require_POST
def apply_coupon(request):
    cart = Cart(request.session)
    if not len(cart):
        return redirect("cart:detail")
    discount_percent = get_offline_payment_discount_percent(request)
    if request.POST.get("coupon_action") == "remove":
        request.session.pop(SESSION_KEY, None)
        messages.info(request, "Cupón quitado.")
    else:
        code = normalize_code(request.POST.get("coupon_code"))
        quote = quote_coupon(code, cart.items(), discount_percent)
        if not code:
            messages.error(request, "Ingresá el código del cupón.")
        elif quote.error:
            messages.error(request, quote.error)
        else:
            request.session[SESSION_KEY] = code
            messages.success(
                request, "Cupón aplicado. Revisá el descuento en el resumen."
            )
    request.session.modified = True
    if request.POST.get("coupon_next") == "checkout":
        # Aplicar o quitar no valida ni envía una compra. Conserva TODOS los
        # campos visibles, también sin JavaScript, sin guardarlos en sesión.
        from orders.forms import CheckoutForm
        from orders.views import _render_checkout

        initial = {
            name: request.POST.get(name, "") for name in CheckoutForm.base_fields
        }
        initial["coupon_code"] = request.session.get(SESSION_KEY, "")
        # Sin JS, el primer envío siguiente vuelve a mostrar el total completo
        # con envío antes de crear el pedido. Con JS se vuelve a cotizar al cargar.
        initial["shipping_quote_token"] = ""
        return _render_checkout(
            request,
            cart,
            CheckoutForm(initial=initial, discount_percent=discount_percent),
            discount_percent,
        )
    return redirect("cart:detail")
