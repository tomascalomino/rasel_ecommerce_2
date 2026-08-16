"""Fuente de verdad de la versión desplegada de RaSel."""

import re
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

VERSION_FILE = Path(__file__).resolve().parents[2] / "app_version"
SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def read_app_version(path=VERSION_FILE) -> str:
    """Lee y valida una versión SemVer estable (major.minor.patch)."""
    try:
        version = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ImproperlyConfigured(f"No se pudo leer la versión en {path}.") from exc
    if not SEMVER_PATTERN.fullmatch(version):
        raise ImproperlyConfigured(
            f"La versión en {path} debe usar el formato SemVer major.minor.patch."
        )
    return version


APP_VERSION = read_app_version()
