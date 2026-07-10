from django.contrib.admin.apps import AdminConfig
from django.contrib.auth.apps import AuthConfig
from django.db.models.signals import post_migrate


class RaselAuthConfig(AuthConfig):
    """Reemplaza a django.contrib.auth: nombre menos técnico en el admin."""

    verbose_name = "Usuarios y roles"


class RaselAdminConfig(AdminConfig):
    """Reemplaza a django.contrib.admin en INSTALLED_APPS."""

    default_site = "config.admin.RaselAdminSite"

    def ready(self):
        super().ready()  # autodiscover: registra todos los ModelAdmin
        from django.contrib import admin
        from django.contrib.auth.models import Group, User

        from .admin import sync_roles
        from .user_admin import RaselUserAdmin

        # Groups fuera del menú: los roles se asignan desde la ficha del
        # usuario y se siembran solos (sync_roles).
        if admin.site.is_registered(Group):
            admin.site.unregister(Group)

        # Alta de usuario con staff pre-tildado.
        if admin.site.is_registered(User):
            admin.site.unregister(User)
        admin.site.register(User, RaselUserAdmin)

        post_migrate.connect(sync_roles, sender=self, dispatch_uid="config.sync_roles")
