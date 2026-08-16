"""Incrementa app_version por patch, feature/minor, major o valor exacto."""

import argparse

from versioning import VERSION_FILE, format_version, parse_version, read_version_file


def next_version(current: tuple[int, int, int], target: str) -> tuple[int, int, int]:
    major, minor, patch = current
    if target == "patch":
        return major, minor, patch + 1
    if target in {"feature", "minor"}:
        return major, minor + 1, 0
    if target == "major":
        return major + 1, 0, 0
    return parse_version(target)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Incrementa la versión SemVer de RaSel."
    )
    parser.add_argument(
        "target",
        help="patch, feature, minor, major o una versión exacta como 2.0.0",
    )
    args = parser.parse_args()

    current_text = read_version_file()
    current = parse_version(current_text)
    updated = next_version(current, args.target.lower())
    if updated <= current:
        parser.error(
            f"la nueva versión {format_version(updated)} debe ser mayor que {current_text}"
        )

    updated_text = format_version(updated)
    VERSION_FILE.write_text(f"{updated_text}\n", encoding="utf-8")
    print(f"Versión actualizada: {current_text} -> {updated_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
