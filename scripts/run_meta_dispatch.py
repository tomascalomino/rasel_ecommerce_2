"""Run the deployed backend from Actions, keeping credentials out of logs."""

import argparse
import hashlib
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

PROFILES = {
    "production": ("main", "https://rasel.ar"),
    "staging": ("bundle_work", "https://rasel-mp-staging.onrender.com"),
}


class DispatchConfigurationError(Exception):
    pass


def database_fingerprint(url):
    """Identify a DB endpoint without storing passwords or connection URLs."""
    parsed = urlsplit(url)
    identity = "|".join(
        (parsed.hostname or "", str(parsed.port or 5432), unquote(parsed.path))
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def validate_configuration(target, environ, app_dir):
    branch, site = PROFILES[target]
    if environ.get("GITHUB_REF") != f"refs/heads/{branch}":
        raise DispatchConfigurationError("Rama no permitida para este entorno.")
    sha = environ.get("META_DISPATCH_SHA", "")
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise DispatchConfigurationError(
            "Falta un META_DISPATCH_SHA completo y verificado."
        )
    database = environ.get("DATABASE_URL", "")
    try:
        parsed = urlsplit(database)
        valid_database = (
            parsed.scheme in {"postgres", "postgresql"}
            and bool(parsed.hostname)
            and parsed.path not in {"", "/"}
            and parse_qs(parsed.query).get("sslmode", [""])[0]
            in {"require", "verify-ca", "verify-full"}
        )
        fingerprint = database_fingerprint(database)
    except ValueError:
        valid_database, fingerprint = False, ""
    expected = environ.get("META_DATABASE_FINGERPRINT", "")
    if (
        not valid_database
        or not re.fullmatch(r"[a-f0-9]{64}", expected)
        or not secrets.compare_digest(fingerprint, expected)
    ):
        raise DispatchConfigurationError(
            "La base no coincide con el entorno o falta TLS."
        )
    if not environ.get("META_CAPI_ACCESS_TOKEN", "").strip():
        raise DispatchConfigurationError("Falta META_CAPI_ACCESS_TOKEN.")
    test_code = environ.get("META_TEST_EVENT_CODE", "").strip()
    order = environ.get("META_DISPATCH_ORDER", "").strip()
    if target == "production" and (test_code or order):
        raise DispatchConfigurationError(
            "Producción requiere código de prueba y orden vacíos."
        )
    if target == "staging" and (
        not test_code or not re.fullmatch(r"[1-9][0-9]{0,11}", order)
    ):
        raise DispatchConfigurationError(
            "Staging requiere código de prueba y una orden explícita."
        )
    if not (app_dir / "backend" / "manage.py").is_file():
        raise DispatchConfigurationError("No se encontró el backend desplegado.")

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(app_dir), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    head = git("rev-parse", "HEAD")
    if head.returncode or head.stdout.strip() != sha:
        raise DispatchConfigurationError(
            "El código descargado no coincide con el SHA configurado."
        )
    if git("merge-base", "--is-ancestor", sha, f"origin/{branch}").returncode:
        raise DispatchConfigurationError("El SHA no pertenece a la rama autorizada.")
    if environ.get("GITHUB_EVENT_NAME") == "push" and environ.get("GITHUB_SHA") != sha:
        raise DispatchConfigurationError(
            "La validación de staging requiere el SHA de este push."
        )
    return site, (int(order) if order else None)


def execute(target, app_dir):
    if os.environ.get("META_DISPATCH_ENABLED") != "1":
        print("Despacho pausado: META_DISPATCH_ENABLED no es 1. Sin acceso a la base.")
        return 0
    site, order = validate_configuration(target, os.environ, app_dir)
    # No production web-session key or payment/email/media credentials are needed.
    os.environ.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "PYTHON_DOTENV_DISABLED": "1",
            "SECRET_KEY": secrets.token_urlsafe(64),
            "DEBUG": "0",
            "SITE_URL": site,
            "ALLOWED_HOSTS": urlsplit(site).hostname,
            "META_PIXEL_ID": "1400536168898337",
            "META_CAPI_ENABLED": "1",
            "MP_CHECKOUT_ENABLED": "0",
            "BREVO_API_KEY": "",
            "ORDER_NOTIFICATION_EMAIL": "",
        }
    )
    sys.path.insert(0, str(app_dir / "backend"))
    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command

    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
        raise DispatchConfigurationError("No se permite despachar sobre SQLite.")
    if settings.SITE_URL != site:
        raise DispatchConfigurationError(
            "La configuración del backend no coincide con el destino."
        )
    print(
        f"Entorno: {target}. Código desplegado verificado. Diagnóstico sin datos personales."
    )
    call_command("send_meta_events", order=order)
    call_command(
        "send_meta_events", send=True, limit=100, order=order, fail_on_problems=True
    )
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=PROFILES, required=True)
    parser.add_argument("--app-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        return execute(args.target, args.app_dir.resolve())
    except DispatchConfigurationError as exc:
        print(f"Despacho detenido: {exc}", file=sys.stderr)
    except Exception as exc:
        # Unexpected DB/HTTP exceptions can contain credentials. Do not log them.
        command_module = sys.modules.get("django.core.management.base")
        if command_module and isinstance(exc, command_module.CommandError):
            print(str(exc), file=sys.stderr)
        else:
            print(
                f"Despacho incompleto ({type(exc).__name__}); detalles sensibles omitidos.",
                file=sys.stderr,
            )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
