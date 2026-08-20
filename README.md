# RaSel

Tienda online de aceite de oliva. Producción: [rasel.ar](https://rasel.ar).

RaSel está construida con Django y PostgreSQL, se despliega en Render y usa
Cloudflare para DNS, proxy e imágenes en R2. El checkout ofrece transferencia y
efectivo. Mercado Pago Checkout Pro está activo en producción con reservas,
webhooks firmados y conciliación manual.

## Empezar aquí

- Agentes: leer y seguir [AGENTS.md](AGENTS.md).
- Funcionamiento actual: [docs/CURRENT_SYSTEM.md](docs/CURRENT_SYSTEM.md).
- Operación, variables y despliegue: [docs/OPERATIONS.md](docs/OPERATIONS.md).
- Historial de cambios aplicados: [docs/CHANGELOG.md](docs/CHANGELOG.md).

## Desarrollo local

```powershell
conda activate rasel_ecommerce_venv
pip install -r requirements.txt
python backend/manage.py migrate
python backend/manage.py runserver
```

Crear `.env` en la raíz con las variables necesarias; consultar el inventario
sin secretos en `docs/OPERATIONS.md`.

## Versionado

La versión actual vive en `app_version`, usa SemVer y aparece en el encabezado
del admin. Todo commit creado durante el desarrollo debe incrementarla,
incluidos cambios de documentación y configuración:

```powershell
python scripts/bump_version.py patch
python scripts/bump_version.py feature
python scripts/bump_version.py major
python scripts/bump_version.py 2.0.0
```

En cada clon, activar el control local versionado una sola vez:

```powershell
python scripts/install_git_hooks.py
```

GitHub Actions vuelve a comprobar cada commit publicado.

## Flujo de publicación

1. Desarrollar, incrementar la versión y pushear a `bundle_work`.
2. Esperar el deploy automático y validar staging.
3. Abrir un PR `bundle_work` → `main`; no pushear directamente a `main`.
4. Superar los checks `app-version` y `promotion-gate` y obtener la aprobación
   manual del responsable del sitio.
5. Integrar exclusivamente con **Create a merge commit**.
6. Avanzar `bundle_work` por fast-forward al nuevo commit de `main` y confirmar
   que ambas ramas apunten al mismo SHA y árbol.
7. Desplegar manualmente en Render el SHA aprobado de `main`.

La rama `main` debe estar protegida mediante un ruleset de GitHub y producción
debe permanecer vinculada a `main` con Auto-Deploy desactivado. El merge commit
de promoción conserva la versión y el árbol del candidato; la sincronización
posterior de `bundle_work` es un fast-forward sin commits nuevos. El
procedimiento completo y sus comprobaciones están en
[docs/OPERATIONS.md](docs/OPERATIONS.md#flujo-obligatorio-de-ramas-y-aprobación).
