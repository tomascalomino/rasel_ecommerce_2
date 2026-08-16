"""Activa los hooks versionados para el clon actual."""

import stat
import subprocess

from versioning import REPOSITORY_ROOT


def main() -> int:
    hook = REPOSITORY_ROOT / ".githooks" / "pre-commit"
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"],
        cwd=REPOSITORY_ROOT,
        check=True,
    )
    print("Hooks de Git activados desde .githooks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
