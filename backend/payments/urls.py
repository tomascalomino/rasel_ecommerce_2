from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("start/<int:order_id>/", views.start, name="start"),
    path("return/<str:status>/", views.payment_return, name="return"),
    path("webhook/", views.webhook, name="webhook"),
]
