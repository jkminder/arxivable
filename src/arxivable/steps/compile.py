"""Step: Compile LaTeX and capture errors/warnings."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass
class CompileResult:
    success: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    log_content: str = ""
    bbl_generated: bool = False
    compiler: str = "pdflatex"


# Packages that require XeLaTeX or LuaLaTeX
_XELATEX_PACKAGES = {"fontspec", "xeCJK", "unicode-math", "polyglossia"}


def detect_compiler(workdir: str, main_tex: str) -> str:
    """Detect which LaTeX compiler to use based on packages.

    Returns 'xelatex', 'lualatex', or 'pdflatex'.
    """
    fpath = os.path.join(workdir, main_tex)
    with open(fpath, encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Check for packages requiring XeLaTeX/LuaLaTeX
    for pkg in _XELATEX_PACKAGES:
        if re.search(rf"\\usepackage\s*(?:\[[^\]]*\])?\s*\{{{re.escape(pkg)}\}}", content):
            # Prefer xelatex if available, fall back to lualatex
            if shutil.which("xelatex"):
                return "xelatex"
            elif shutil.which("lualatex"):
                return "lualatex"
            # Fall through to pdflatex (will likely fail, but we'll report it)

    return "pdflatex"


def run_latex(
    workdir: str, main_tex: str, compiler: str = "pdflatex", verbose: bool = False
) -> subprocess.CompletedProcess:
    """Run a LaTeX compiler once."""
    proc = subprocess.run(
        [compiler, "-interaction=nonstopmode", main_tex],
        cwd=workdir,
        capture_output=True,
        timeout=120,
    )
    # Decode with replacement to handle non-UTF-8 output from TeX
    proc.stdout = proc.stdout.decode("utf-8", errors="replace") if isinstance(proc.stdout, bytes) else proc.stdout
    proc.stderr = proc.stderr.decode("utf-8", errors="replace") if isinstance(proc.stderr, bytes) else proc.stderr
    return proc


def run_bibtex(workdir: str, main_tex: str, verbose: bool = False) -> subprocess.CompletedProcess:
    """Run bibtex."""
    aux_name = os.path.splitext(main_tex)[0]
    proc = subprocess.run(
        ["bibtex", aux_name],
        cwd=workdir,
        capture_output=True,
        timeout=60,
    )
    proc.stdout = proc.stdout.decode("utf-8", errors="replace") if isinstance(proc.stdout, bytes) else proc.stdout
    proc.stderr = proc.stderr.decode("utf-8", errors="replace") if isinstance(proc.stderr, bytes) else proc.stderr
    return proc


def compile_latex(
    workdir: str,
    main_tex: str,
    needs_bibtex: bool = False,
    verbose: bool = False,
) -> CompileResult:
    """Full compilation: latex → bibtex (if needed) → latex × 2."""
    result = CompileResult()

    # Auto-detect compiler
    compiler = detect_compiler(workdir, main_tex)
    result.compiler = compiler
    if compiler != "pdflatex" and verbose:
        print(f"  Detected {compiler} requirement (fontspec/xeCJK/etc.)")

    try:
        # First pass
        if verbose:
            print(f"  Running {compiler} (pass 1)...")
        run_latex(workdir, main_tex, compiler, verbose)

        if needs_bibtex:
            if verbose:
                print("  Running bibtex...")
            bib_proc = run_bibtex(workdir, main_tex, verbose)
            if bib_proc.returncode != 0 and verbose:
                print(f"  bibtex warnings: {bib_proc.stderr[:200]}")
            result.bbl_generated = True

        # Second and third passes
        for i in range(2):
            if verbose:
                print(f"  Running {compiler} (pass {i + 2})...")
            run_latex(workdir, main_tex, compiler, verbose)

        # Parse the log
        log_path = os.path.join(workdir, os.path.splitext(main_tex)[0] + ".log")
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8", errors="replace") as f:
                result.log_content = f.read()

        _parse_log(result)

    except subprocess.TimeoutExpired:
        result.success = False
        result.errors.append("Compilation timed out")
    except FileNotFoundError:
        result.success = False
        result.errors.append(f"{compiler} not found")

    return result


def _parse_log(result: CompileResult) -> None:
    """Parse LaTeX log for errors and warnings."""
    for line in result.log_content.split("\n"):
        line_stripped = line.strip()
        if line_stripped.startswith("! "):
            result.errors.append(line_stripped)
            result.success = False
        elif "Warning" in line and "Overfull" not in line and "Underfull" not in line:
            result.warnings.append(line_stripped)
