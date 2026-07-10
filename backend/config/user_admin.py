"""ModelAdmin de usuarios.

En módulo aparte (no en config.admin): importar django.contrib.auth.admin
desde config.admin crearía un import circular, porque auth.admin está a
mitad de importarse cuando el sitio default resuelve config.admin.RaselAdminSite.
Este módulo se importa recién en RaselAdminConfig.ready(), con auth.admin
ya cargado por completo.
"""

from django.contrib.auth.admin import UserAdmin


class RaselUserAdmin(UserAdmin):
    """Alta de usuario con la tilde de staff visible y pre-marcada: los
    usuarios que se crean desde el admin son para administrar el panel
    (se puede destildar en el mismo formulario)."""

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "usable_password", "password1", "password2", "is_staff"),
            },
        ),
    )

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial.setdefault("is_staff", True)
        return initial
