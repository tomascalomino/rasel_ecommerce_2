from django.urls import path
from . import views

app_name = "cart"

urlpatterns = [
    path("", views.cart_detail, name="detail"),
    path("add/", views.cart_add, name="add"),
    path("update/", views.cart_update, name="update"),
    path("remove/", views.cart_remove, name="remove"),
]
