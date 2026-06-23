from django import forms
from django.conf import settings

from shipping.services import normalize_cp


class CheckoutForm(forms.Form):
    full_name = forms.CharField(max_length=120)
    email = forms.EmailField()
    phone = forms.CharField(max_length=30, required=False)

    address_line = forms.CharField(max_length=200)
    city = forms.CharField(max_length=100)
    postal_code = forms.CharField(max_length=20)

    def clean_postal_code(self):
        raw = self.cleaned_data["postal_code"]
        if normalize_cp(raw) is None:
            raise forms.ValidationError(
                "Ingresá un código postal válido (ej. 1744 o C1744)."
            )
        return raw

    PAYMENT_CHOICES = [
        ("mp", "Mercado Pago"),
        ("transfer", "Transferencia Bancaria"),
    ]
    payment_method = forms.ChoiceField(
        choices=PAYMENT_CHOICES, widget=forms.RadioSelect, initial="mp"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Con MercadoPago apagado, la única opción válida es transferencia.
        if not settings.MP_ENABLED:
            self.fields["payment_method"].choices = [
                ("transfer", "Transferencia Bancaria"),
            ]
            self.fields["payment_method"].initial = "transfer"
