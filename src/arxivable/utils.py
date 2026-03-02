"""Shared helpers: dependency checks, logging, path utilities."""

from __future__ import annotations

import shutil
import subprocess
import sys


def check_dependencies() -> None:
    """Verify pdflatex, bibtex, and git are available."""
    missing = []
    for cmd in ("pdflatex", "bibtex", "git"):
        if shutil.which(cmd) is None:
            missing.append(cmd)
    if missing:
        print(f"Error: missing required commands: {', '.join(missing)}")
        print()
        if "pdflatex" in missing or "bibtex" in missing:
            print("Install a TeX distribution:")
            print("  macOS:  brew install --cask mactex")
            print("  Ubuntu: sudo apt install texlive-full")
        if "git" in missing:
            print("Install git:")
            print("  macOS:  brew install git")
            print("  Ubuntu: sudo apt install git")
        sys.exit(1)


def is_git_url(source: str) -> bool:
    """Check whether source looks like a git URL by running git ls-remote."""
    if not (
        source.startswith("git@")
        or source.startswith("https://")
        or source.startswith("http://")
        or source.startswith("ssh://")
        or source.endswith(".git")
    ):
        return False
    try:
        subprocess.run(
            ["git", "ls-remote", "--exit-code", source],
            capture_output=True,
            timeout=30,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def step_print(step: int, total: int, msg: str) -> None:
    """Print a step progress indicator."""
    print(f"[{step}/{total}] {msg}")


def format_size(nbytes: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"
