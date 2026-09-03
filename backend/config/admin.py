"""
Admin personalizado de RaSel.

- RaselAdminSite: branding en español, menú ordenado por importancia y
  dashboard con resumen del negocio (pendientes, ventas, últimas órdenes).
- sync_roles: siembra los grupos "Operador" y "Solo lectura" con sus
  permisos. Idempotente: corre en cada `migrate` (señal post_migrate).
"""

from datetime import timedelta

from django.apps import apps as global_apps
from django.contrib import admin
from django.db.models import Count, Sum
from django.utils import timezone

from .version import APP_VERSION

ROLE_OPERATOR = "Operador"
ROLE_READONLY = "Solo lectura"

# Matriz de permisos por rol ("app.modelo": acciones). Es la fuente de verdad
# de los roles y se documenta para el usuario en el panel "Roles y accesos"
# del dashboard (templates/admin/rasel_index.html) — mantener ambos en sintonía.
_OPERATOR_MATRIX = {
    "orders.order": ("view", "change"),
    "orders.orderitem": ("view", "change"),
    "shop.category": ("view", "add", "change"),
    "shop.product": ("view", "add", "change"),
    "shop.variant": ("view", "add", "change"),
    "shop.commercialsettings": ("view", "change"),
    "shipping.shippingzone": ("view", "add", "change"),
    # Las reglas de CP se editan inline dentro de la zona; sin "delete" no se
    # podría corregir un rango mal cargado.
    "shipping.postalcoderule": ("view", "add", "change", "delete"),
    "shipping.pickuppoint": ("view", "add", "change"),
}
_READONLY_MATRIX = {model: ("view",) for model in _OPERATOR_MATRIX}


def sync_roles(sender=None, **kwargs):
    """Crea/actualiza los grupos de roles según la matriz.

    Autoritativo: un permiso quitado de la matriz se revoca en el próximo
    migrate. Los permisos de las apps se crean acá mismo porque esta señal
    puede correr antes que el create_permissions de contrib.auth (el orden de
    los receivers de post_migrate sigue el orden de INSTALLED_APPS).
    """
    from django.contrib.auth.management import create_permissions
    from django.contrib.auth.models import Group, Permission

    for app_label in ("shop", "orders", "shipping"):
        create_permissions(global_apps.get_app_config(app_label), verbosity=0)

    for name, matrix in ((ROLE_OPERATOR, _OPERATOR_MATRIX), (ROLE_READONLY, _READONLY_MATRIX)):
        group, _ = Group.objects.get_or_create(name=name)
        perms = []
        for model_key, actions in matrix.items():
            app_label, model_name = model_key.split(".")
            perms.extend(
                Permission.objects.filter(
                    content_type__app_label=app_label,
                    codename__in=[f"{action}_{model_name}" for action in actions],
                )
            )
        group.permissions.set(perms)


class RaselAdminSite(admin.AdminSite):
    site_header = "RaSel — Administración"
    site_title = "Admin RaSel"
    index_title = "Panel de control"
    index_template = "admin/rasel_index.html"

    # Menú por importancia: primero lo que se usa todos los días.
    _APP_ORDER = ("orders", "shop", "shipping", "auth")
    _MODEL_ORDER = {
        "shop": ("commercialsettings", "product", "variant", "category"),
        "shipping": ("shippingzone", "pickuppoint"),
    }

    def each_context(self, request):
        context = super().each_context(request)
        context["app_version"] = APP_VERSION
        return context

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        app_pos = {label: i for i, label in enumerate(self._APP_ORDER)}
        app_list.sort(key=lambda app: app_pos.get(app["app_label"], len(app_pos)))
        for app in app_list:
            model_order = self._MODEL_ORDER.get(app["app_label"])
            if model_order:
                model_pos = {name: i for i, name in enumerate(model_order)}
                app["models"].sort(
                    key=lambda m: model_pos.get(m["object_name"].lower(), len(model_pos))
                )
        return app_list

    def index(self, request, extra_context=None):
        extra_context = {**(extra_context or {}), **self._dashboard_context()}
        return super().index(request, extra_context=extra_context)

    def _dashboard_context(self):
        from orders.models import Order

        now = timezone.localtime()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week = today - timedelta(days=today.weekday())
        month = today.replace(day=1)

        sold = Order.objects.filter(status__in=("paid", "shipped"))

        def sales_since(start):
            data = sold.filter(created_at__gte=start).aggregate(
                total=Sum("total_amount"), count=Count("id")
            )
            return {"total": data["total"] or 0, "count": data["count"] or 0}

        return {
            "dash_pending_count": Order.objects.filter(status="pending").count(),
            "dash_sales_today": sales_since(today),
            "dash_sales_week": sales_since(week),
            "dash_sales_month": sales_since(month),
            "dash_recent_orders": Order.objects.order_by("-created_at")[:8],
        }
