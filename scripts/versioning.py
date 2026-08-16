"""Utilidades compartidas para el versionado SemVer del repositorio."""

import re
from pathlib import Path

SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPOSITORY_ROOT / "app_version"


def parse_version(value: str) -> tuple[int, int, int]:
    normalized = value.strip()
    match = SEMVER_PATTERN.fullmatch(normalized)
    if not match:
        raise ValueError(
            f"'{normalized}' no es una versión válida; use major.minor.patch."
        )
    return tuple(int(part) for part in match.groups())


def format_version(parts: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in parts)


def read_version_file() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()
