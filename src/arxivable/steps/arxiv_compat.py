"""Step: arXiv compatibility fixes."""

from __future__ import annotations

import os
import re

from arxivable.utils import format_size


def ensure_pdfoutput(workdir: str, main_tex: str, verbose: bool = False) -> bool:
    """Ensure \\pdfoutput=1 appears in the first 5 lines. Returns True if added."""
    fpath = os.path.join(workdir, main_tex)
    with open(fpath, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # Check first 5 lines
    for line in lines[:5]:
        if re.search(r"\\pdfoutput\s*=\s*1", line):
            if verbose:
                print("  \\pdfoutput=1 already present")
            return False

    # Insert after \documentclass line
    insert_idx = 0
    for i, line in enumerate(lines):
        if re.match(r"\s*\\documentclass", line):
            insert_idx = i + 1
            break

    lines.insert(insert_idx, "\\pdfoutput=1\n")
    with open(fpath, "w", encoding="utf-8") as f:
        f.writelines(lines)

    if verbose:
        print(f"  Added \\pdfoutput=1 at line {insert_idx + 1}")
    return True


def check_bbl_exists(workdir: str, main_tex: str) -> bool:
    """Check if .bbl file exists for the main .tex file."""
    bbl_name = os.path.splitext(main_tex)[0] + ".bbl"
    return os.path.isfile(os.path.join(workdir, bbl_name))


def check_bib_exists(workdir: str) -> str | None:
    """Find .bib file in workdir. Returns path or None."""
    for root, _dirs, files in os.walk(workdir):
        for fname in files:
            if fname.endswith(".bib"):
                return os.path.relpath(os.path.join(root, fname), workdir)
    return None


def check_size_warnings(workdir: str, verbose: bool = False) -> list[str]:
    """Check for files > 10MB and total > 50MB. Returns warning messages."""
    warnings: list[str] = []
    total_size = 0

    for root, _dirs, files in os.walk(workdir):
        for fname in files:
            fpath = os.path.join(root, fname)
            size = os.path.getsize(fpath)
            total_size += size
            if size > 10 * 1024 * 1024:
                rel = os.path.relpath(fpath, workdir)
                warnings.append(f"  Large file: {rel} ({format_size(size)})")

    if total_size > 50 * 1024 * 1024:
        warnings.append(f"  Total size {format_size(total_size)} exceeds arXiv 50MB limit")

    return warnings
