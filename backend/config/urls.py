"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from shop.views import robots_txt, sitemap_xml, healthz
from shipping.views import shipping_info

urlpatterns = [
    path("healthz", healthz),
    path("robots.txt", robots_txt),
    path("sitemap.xml", sitemap_xml),
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("about/", TemplateView.as_view(template_name="about.html"), name="about"),
    path("contact/", TemplateView.as_view(template_name="contact.html"), name="contact"),
    path("envios/", shipping_info, name="shipping_info"),
    # Legales
    path("terminos/", TemplateView.as_view(template_name="legal/terms.html"), name="terms"),
    path("privacidad/", TemplateView.as_view(template_name="legal/privacy.html"), name="privacy"),
    path("devoluciones/", TemplateView.as_view(template_name="legal/returns.html"), name="returns"),
    path("arrepentimiento/", TemplateView.as_view(template_name="legal/regret.html"), name="regret"),
    path("shop/", include("shop.urls")),
    path("cart/", include("cart.urls")),
    path("orders/", include("orders.urls")),
    path("payments/", include("payments.urls")),
    path("shipping/", include("shipping.urls")),
    path("admin/", admin.site.urls),
]

if settings.SERVE_MEDIA:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {
            'document_root': settings.MEDIA_ROOT,
        }),
    ]
