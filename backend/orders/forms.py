from django import forms
from django.conf import settings

from config.pricing import get_offline_payment_discount_percent
from shipping.models import PickupPoint
from shipping.services import normalize_cp


class CheckoutForm(forms.Form):
    DELIVERY_CHOICES = [
        ("ship", "Envío a domicilio"),
        ("pickup", "Retiro sin cargo en punto de retiro"),
    ]
    delivery_method = forms.ChoiceField(
        choices=DELIVERY_CHOICES, widget=forms.RadioSelect, initial="ship"
    )
    pickup_point = forms.ModelChoiceField(
        queryset=PickupPoint.objects.none(),
        required=False,
        widget=forms.RadioSelect,
        empty_label=None,
    )

    full_name = forms.CharField(max_length=120, label="Nombre y apellido")
    email = forms.EmailField(label="Email")
    phone = forms.CharField(max_length=30, required=False, label="Teléfono")

    # Requeridos solo para envío a domicilio (ver clean()).
    address_line = forms.CharField(max_length=200, required=False, label="Dirección")
    # Opcional: piso, depto, timbre, referencias. Nunca es obligatorio.
    address_extra = forms.CharField(
        max_length=200,
        required=False,
        label="Piso, depto u otra información (opcional)",
        widget=forms.TextInput(attrs={"placeholder": "Ej. Piso 3, depto B, timbre 2"}),
    )
    city = forms.CharField(max_length=100, required=False, label="Ciudad")
    postal_code = forms.CharField(max_length=20, required=False, label="Código postal")

    PAYMENT_CHOICES = [
        ("mp", "Mercado Pago"),
        ("transfer", "Transferencia Bancaria"),
        ("cod", "Efectivo (al recibir o al retirar)"),
    ]
    payment_method = forms.ChoiceField(
        choices=PAYMENT_CHOICES, widget=forms.RadioSelect, initial="mp"
    )

    def __init__(self, *args, discount_percent=None, **kwargs):
        super().__init__(*args, **kwargs)
        if discount_percent is None:
            discount_percent = get_offline_payment_discount_percent()
        self.offline_discount_percent = int(discount_percent)
        suffix = (
            f" — mínimo {self.offline_discount_percent}% de descuento"
            if self.offline_discount_percent > 0
            else ""
        )
        payment_choices = [
            self.PAYMENT_CHOICES[0],
            ("transfer", f"{self.PAYMENT_CHOICES[1][1]}{suffix}"),
            ("cod", f"{self.PAYMENT_CHOICES[2][1]}{suffix}"),
        ]
        self.fields["payment_method"].choices = payment_choices
        # Queryset fresco en cada instancia (no a nivel de clase).
        self.fields["pickup_point"].queryset = PickupPoint.objects.filter(
            is_active=True
        )
        # Con MercadoPago apagado quedan transferencia y efectivo.
        if not settings.MP_CHECKOUT_ENABLED:
            self.fields["payment_method"].choices = [
                payment_choices[1],
                payment_choices[2],
            ]
            self.fields["payment_method"].initial = "transfer"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("delivery_method") == "pickup":
            if not cleaned.get("pickup_point"):
                self.add_error("pickup_point", "Elegí el punto de retiro.")
            # La orden de retiro no usa dirección: se guarda vacía.
            cleaned["address_line"] = ""
            cleaned["address_extra"] = ""
            cleaned["city"] = ""
            cleaned["postal_code"] = ""
        else:
            for field in ("address_line", "city", "postal_code"):
                if not cleaned.get(field):
                    self.add_error(
                        field, "Este campo es obligatorio para envío a domicilio."
                    )
            if cleaned.get("postal_code") and normalize_cp(cleaned["postal_code"]) is None:
                self.add_error(
                    "postal_code",
                    "Ingresá un código postal válido (ej. 1744 o C1744).",
                )
        return cleaned
