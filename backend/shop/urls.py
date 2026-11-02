from django.urls import path
from . import views

app_name = "shop"

urlpatterns = [
    path("gift-status/", views.gift_status, name="gift_status"),
    path("", views.product_list, name="product_list"),
    path("p/<slug:slug>/", views.product_detail, name="product_detail"),
]
