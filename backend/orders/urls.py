from django.urls import path
from . import views

app_name = "orders"

urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
    path("confirmation/<int:order_id>/", views.confirmation, name="confirmation"),
    path("transfer/<int:order_id>/", views.transfer_info, name="transfer_info"),
    path("cod/<int:order_id>/", views.cod_info, name="cod_info"),
]
