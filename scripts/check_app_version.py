"""Valida que cada commit introduzca un incremento SemVer de app_version."""

import argparse
import subprocess
import sys

from versioning import parse_version

VERSION_PATH = "app_version"


def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def git_text(*arguments: str, check: bool = True) -> str:
    return git(*arguments, check=check).stdout.strip()


def version_at(revision: str) -> str | None:
    spec = f":{VERSION_PATH}" if revision == ":" else f"{revision}:{VERSION_PATH}"
    result = git("show", spec, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def validate_increment(previous: str | None, current: str, label: str) -> list[str]:
    errors = []
    try:
        current_parts = parse_version(current)
    except ValueError as exc:
        return [f"{label}: {exc}"]
    if previous is None:
        return errors
    try:
        previous_parts = parse_version(previous)
    except ValueError as exc:
        return [f"{label}: la versión anterior es inválida: {exc}"]
    if current_parts <= previous_parts:
        errors.append(
            f"{label}: app_version debe aumentar; {current} no es mayor que {previous}."
        )
    return errors


def check_staged() -> list[str]:
    staged = {
        path.replace("\\", "/")
        for path in git_text(
            "diff", "--cached", "--name-only", "--diff-filter=ACMR"
        ).splitlines()
    }
    if VERSION_PATH not in staged:
        return [
            "Cada commit debe incluir un incremento de app_version. "
            "Ejecute: python scripts/bump_version.py patch|feature|major"
        ]

    current = version_at(":")
    if current is None:
        return ["No se pudo leer app_version desde el índice de Git."]
    previous = version_at("HEAD")
    return validate_increment(previous, current, "commit preparado")


def check_commit(commit: str) -> list[str]:
    short = git_text("rev-parse", "--short", commit)
    subject = git_text("show", "-s", "--format=%s", commit)
    label = f"{short} ({subject})"
    current = version_at(commit)
    parents = git_text("show", "-s", "--format=%P", commit).split()
    parent_versions = [version_at(parent) for parent in parents]

    if current is None:
        if any(version is not None for version in parent_versions):
            return [f"{label}: app_version fue eliminado."]
        return []  # Historial anterior a la incorporación del versionado.

    errors = validate_increment(None, current, label)
    for previous in parent_versions:
        errors.extend(validate_increment(previous, current, label))
    return errors


def check_range(revision_range: str) -> list[str]:
    commits = git_text("rev-list", "--reverse", revision_range).splitlines()
    errors = []
    for commit in commits:
        errors.extend(check_commit(commit))

    head = revision_range.rsplit("..", 1)[-1]
    if version_at(head) is None:
        errors.append(f"El extremo {head} no contiene {VERSION_PATH}.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--range", dest="revision_range")
    args = parser.parse_args()

    errors = check_staged() if args.staged else check_range(args.revision_range)
    if errors:
        print("Error de versionado:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Versionado SemVer válido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
