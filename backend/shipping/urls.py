from django.urls import path

from . import views

app_name = "shipping"

urlpatterns = [
    path("quote/", views.quote, name="quote"),
    path("promotion-status/", views.promotion_status, name="promotion_status"),
]
