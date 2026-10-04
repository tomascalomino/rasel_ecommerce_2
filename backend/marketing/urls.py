from django.urls import path

from . import views

app_name = "marketing"
urlpatterns = [
    path("consent/", views.consent, name="consent"),
    path("claim/", views.claim, name="claim"),
]
