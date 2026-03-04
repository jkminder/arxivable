"""Step: Visual PDF diff using diff-pdf."""

from __future__ import annotations

import shutil
import subprocess


def check_diff_pdf() -> bool:
    """Check if diff-pdf is available on PATH."""
    return shutil.which("diff-pdf") is not None


def run_pdf_diff(
    ref_pdf: str, cleaned_pdf: str, diff_output: str | None = None
) -> bool:
    """Compare two PDFs visually using diff-pdf.

    Returns True if PDFs are visually identical (exit code 0).
    """
    cmd = ["diff-pdf"]
    if diff_output:
        cmd.append(f"--output-diff={diff_output}")
    cmd.extend([ref_pdf, cleaned_pdf])

    result = subprocess.run(cmd, capture_output=True, timeout=120)
    return result.returncode == 0
