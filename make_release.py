"""Bundle Optima into a distributable .zip — the "installation file" listed in
the submission instructions.

Run from the project root:

    python make_release.py

Produces ``dist/Optima-v1.0.zip`` containing exactly what an evaluator needs
to unzip and use, and nothing they don't (no caches, no virtual env, no
on-disk user data).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
VERSION = "v1.0"
RELEASE_NAME = f"Optima-{VERSION}"

# Things we explicitly INCLUDE in the release archive.
INCLUDE = [
    "app",
    "docs",
    "feedback",
    "prototypes",
    "run.py",
    "generate_docx.py",
    "install.sh",
    "install.bat",
    "make_release.py",
    "requirements.txt",
    "README.md",
]

# Things we explicitly EXCLUDE even if they live inside an included path.
EXCLUDE_NAMES = {
    "__pycache__", ".DS_Store", ".pytest_cache", ".venv", "node_modules",
    ".git", "dist",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _should_skip(path: Path) -> bool:
    for part in path.parts:
        if part in EXCLUDE_NAMES:
            return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    # Skip per-user data files but keep the directory structure.
    if path.parts[:2] == ("data", "users") and path.suffix == ".json":
        return True
    return False


def _gather(root: Path) -> list[Path]:
    paths: list[Path] = []
    for entry in INCLUDE:
        target = root / entry
        if not target.exists():
            print(f"  skip (missing): {entry}")
            continue
        if target.is_file():
            paths.append(target)
        else:
            for p in target.rglob("*"):
                if p.is_file() and not _should_skip(p.relative_to(root)):
                    paths.append(p)
    return paths


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)
    archive = DIST / f"{RELEASE_NAME}.zip"
    files = _gather(ROOT)
    print(f"Bundling {len(files)} files into {archive}")
    with ZipFile(archive, "w", ZIP_DEFLATED) as zf:
        for f in sorted(files):
            arcname = Path(RELEASE_NAME) / f.relative_to(ROOT)
            zf.write(f, arcname.as_posix())
    size_kb = archive.stat().st_size / 1024
    print(f"Done. {archive.name} — {size_kb:,.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
