from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("start/<uuid:draft_id>/", views.start, name="start"),
    path("return/<str:result>/", views.payment_return, name="return"),
    path("webhook/", views.webhook, name="webhook"),
]
