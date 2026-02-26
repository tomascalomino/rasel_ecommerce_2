from django import forms


class CheckoutForm(forms.Form):
    full_name = forms.CharField(max_length=120)
    email = forms.EmailField()
    phone = forms.CharField(max_length=30, required=False)

    address_line = forms.CharField(max_length=200)
    city = forms.CharField(max_length=100)
    postal_code = forms.CharField(max_length=20)
