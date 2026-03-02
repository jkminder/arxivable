"""Main orchestration: runs all pipeline steps in order."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

from arxivable.utils import check_dependencies, format_size, is_git_url, step_print


TOTAL_STEPS = 8  # base steps (without optional claude check)

JUNK_PATTERNS = {
    ".git",
    ".gitignore",
    ".DS_Store",
    "Thumbs.db",
    "build",
    "output",
}

JUNK_PREFIXES = ("._",)

JUNK_EXTENSIONS = {
    ".aux",
    ".log",
    ".out",
    ".synctex.gz",
    ".fdb_latexmk",
    ".fls",
    ".toc",
    ".blg",
    ".bcf",
    ".run.xml",
}


def _detect_main_tex(workdir: str, hint: str | None) -> str:
    """Auto-detect the main .tex file."""
    if hint:
        path = os.path.join(workdir, hint)
        if os.path.isfile(path):
            return hint
        raise SystemExit(f"Error: specified main file not found: {hint}")

    candidates: list[str] = []
    for fname in os.listdir(workdir):
        if not fname.endswith(".tex"):
            continue
        fpath = os.path.join(workdir, fname)
        with open(fpath, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= 20:
                    break
                if re.search(r"\\documentclass", line):
                    candidates.append(fname)
                    break

    if not candidates:
        raise SystemExit("Error: no .tex file with \\documentclass found")

    # Prefer main.tex
    if "main.tex" in candidates:
        return "main.tex"

    if len(candidates) == 1:
        return candidates[0]

    raise SystemExit(
        f"Error: multiple candidates found: {', '.join(candidates)}. "
        f"Use --main to specify."
    )


def _clean_junk(workdir: str, verbose: bool = False) -> int:
    """Remove junk/hidden files and build artifacts. Returns count."""
    count = 0
    for root, dirs, files in os.walk(workdir, topdown=True):
        # Remove junk directories
        to_remove = []
        for d in dirs:
            _, dext = os.path.splitext(d)
            if d in JUNK_PATTERNS or d.startswith(".") or dext == ".app":
                dpath = os.path.join(root, d)
                shutil.rmtree(dpath)
                count += 1
                if verbose:
                    print(f"  Removed dir: {os.path.relpath(dpath, workdir)}/")
                to_remove.append(d)
        for d in to_remove:
            dirs.remove(d)

        # Remove junk files
        for fname in files:
            fpath = os.path.join(root, fname)
            _, ext = os.path.splitext(fname)
            if (
                fname in JUNK_PATTERNS
                or any(fname.startswith(p) for p in JUNK_PREFIXES)
                or ext in JUNK_EXTENSIONS
            ):
                os.remove(fpath)
                count += 1
                if verbose:
                    print(f"  Removed: {os.path.relpath(fpath, workdir)}")

    return count


def _git_snapshot(workdir: str) -> None:
    """Initialize a git repo in workdir and commit current state as baseline."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "arxivable",
        "GIT_AUTHOR_EMAIL": "arxivable@local",
        "GIT_COMMITTER_NAME": "arxivable",
        "GIT_COMMITTER_EMAIL": "arxivable@local",
    }
    subprocess.run(["git", "init"], cwd=workdir, capture_output=True, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=workdir, capture_output=True, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-m", "baseline", "--allow-empty"],
        cwd=workdir, capture_output=True, check=True, env=env,
    )


def _git_cleanup(workdir: str) -> None:
    """Remove the temporary .git directory from the workdir."""
    git_dir = os.path.join(workdir, ".git")
    if os.path.isdir(git_dir):
        shutil.rmtree(git_dir)


def run_pipeline(
    source: str,
    output: str | None,
    main_file: str | None,
    force: bool,
    check_with_claude: bool,
    keep_temp: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Run the full arxivable pipeline."""
    from arxivable.steps.clone import prepare_workdir
    from arxivable.steps.todos import (
        discover_todos,
        find_todo_invocations,
        validate_todos,
        remove_todo_infrastructure,
        remove_borderline_command,
        find_borderline_usages,
    )
    from arxivable.steps.comments import run_strip_comments
    from arxivable.steps.unused_files import remove_unused_files
    from arxivable.steps.arxiv_compat import (
        ensure_pdfoutput,
        check_bbl_exists,
        check_bib_exists,
        check_size_warnings,
    )
    from arxivable.steps.compile import compile_latex, detect_compiler
    from arxivable.steps.claude_check import verify_changes as claude_verify
    from arxivable.steps.package import clean_build_artifacts, create_zip

    # Summary tracking
    summary = {
        "source": os.path.abspath(os.path.expanduser(source)) if not is_git_url(source) else source,
        "comments_stripped": [],
        "todo_summary": None,
        "files_removed": [],
        "fixes": [],
        "compile_warnings": 0,
        "compile_errors": 0,
        "output": None,
        "output_size": 0,
    }

    # ── Step 1: Check dependencies ──
    step_print(1, TOTAL_STEPS, "Checking dependencies...")
    check_dependencies()

    # ── Step 2: Prepare working directory ──
    step_print(2, TOTAL_STEPS, "Preparing working directory...")
    workdir, project_name = prepare_workdir(source, verbose)

    if output is None:
        output = os.path.expanduser(f"~/Downloads/{project_name}_arxiv.zip")

    try:
        # ── Step 3: Auto-detect main .tex & clean junk ──
        step_print(3, TOTAL_STEPS, "Detecting main file & cleaning junk...")
        main_tex = _detect_main_tex(workdir, main_file)
        if verbose:
            print(f"  Main file: {main_tex}")

        junk_count = _clean_junk(workdir, verbose)
        if verbose:
            print(f"  Removed {junk_count} junk files/dirs")

        # Snapshot clean state for diffing (used by claude check)
        if check_with_claude:
            try:
                _git_snapshot(workdir)
            except subprocess.CalledProcessError:
                if verbose:
                    print("  Warning: could not create git snapshot for diff")

        # ── Step 4: Detect and remove todos ──
        step_print(4, TOTAL_STEPS, "Processing todo commands...")
        todo_info = discover_todos(workdir, verbose)
        find_todo_invocations(workdir, main_tex, todo_info, verbose)

        if todo_info.has_active_todos and not dry_run:
            validate_todos(todo_info, force)

        if dry_run:
            if todo_info.commands:
                print(f"  Would remove {len(todo_info.commands)} todo command definitions")
                if todo_info.invocations:
                    print(f"  Would remove {len(todo_info.invocations)} todo invocations")
        else:
            if todo_info.todonotes_file:
                todo_result = remove_todo_infrastructure(workdir, main_tex, todo_info, verbose)
                summary["todo_summary"] = todo_result

        if todo_info.borderline_color_commands and not dry_run:
            borderline_removed = _prompt_borderline_commands(
                workdir, main_tex, todo_info.borderline_color_commands, verbose,
            )
            if borderline_removed:
                summary.setdefault("borderline_removed", []).extend(borderline_removed)

        # ── Step 5: Strip comments ──
        step_print(5, TOTAL_STEPS, "Stripping comments...")
        modified_files = run_strip_comments(workdir, main_tex, verbose, dry_run)
        summary["comments_stripped"] = modified_files
        if dry_run:
            print(f"  Would strip comments from {len(modified_files)} files")

        # ── Step 6: Remove unused files ──
        step_print(6, TOTAL_STEPS, "Removing unused files...")
        removed = remove_unused_files(workdir, main_tex, verbose, dry_run)
        summary["files_removed"] = removed
        if dry_run:
            if removed:
                print(f"  Would remove {len(removed)} unused files:")
                for f in removed[:10]:
                    print(f"    - {f}")
                if len(removed) > 10:
                    print(f"    ... and {len(removed) - 10} more")

        if dry_run:
            print("\nDry run complete. No changes were applied.")
            return

        # ── Step 7: arXiv compatibility ──
        step_print(7, TOTAL_STEPS, "Applying arXiv compatibility fixes...")

        # Detect compiler first — \pdfoutput=1 only needed for pdflatex
        compiler = detect_compiler(workdir, main_tex)
        if compiler != "pdflatex" and verbose:
            print(f"  Detected {compiler} requirement (fontspec/xeCJK/etc.)")

        if compiler == "pdflatex":
            pdfoutput_added = ensure_pdfoutput(workdir, main_tex, verbose)
            if pdfoutput_added:
                summary["fixes"].append("Added \\pdfoutput=1")

        bbl_existed = check_bbl_exists(workdir, main_tex)
        bib_file = check_bib_exists(workdir)
        needs_bibtex = not bbl_existed and bib_file is not None

        if needs_bibtex:
            summary["fixes"].append(f"Generated .bbl from {bib_file}")

        size_warnings = check_size_warnings(workdir, verbose)
        for w in size_warnings:
            print(f"  Warning: {w}")

        # ── Step 8: Compile ──
        step_print(8, TOTAL_STEPS, f"Compiling ({compiler})...")
        compile_result = compile_latex(workdir, main_tex, needs_bibtex, verbose)

        if compile_result.errors:
            print("  Compilation errors:")
            for err in compile_result.errors[:10]:
                print(f"    {err}")
        summary["compile_warnings"] = len(compile_result.warnings)
        summary["compile_errors"] = len(compile_result.errors)

        # Optional: Claude verification of all changes
        if check_with_claude:
            print("[*] Verifying changes with Claude...")
            analysis = claude_verify(
                workdir=workdir,
                todo_commands=list(todo_info.commands.keys()),
                todo_invocations_removed=len(todo_info.invocations),
                borderline_commands={},  # already handled interactively
                files_removed=removed,
                comments_stripped=modified_files,
                compile_warnings=compile_result.warnings,
                compile_errors=compile_result.errors,
                verbose=verbose,
            )
            _git_cleanup(workdir)
            if analysis:
                summary["claude_verification"] = analysis

        # ── Clean artifacts and package ──
        clean_build_artifacts(workdir, main_tex, verbose)
        zip_size = create_zip(workdir, output, verbose)
        summary["output"] = output
        summary["output_size"] = zip_size

        # ── Print summary ──
        _print_summary(summary)

    finally:
        if keep_temp:
            print(f"\nTemp directory kept at: {workdir}")
        else:
            # workdir is inside a temp parent
            parent = os.path.dirname(workdir)
            shutil.rmtree(parent, ignore_errors=True)


def _prompt_borderline_commands(
    workdir: str,
    main_tex: str,
    borderline: dict[str, str],
    verbose: bool,
) -> list[str]:
    """Interactively ask the user about each borderline color-marker command.

    Returns list of command names that were removed.
    """
    from arxivable.steps.todos import remove_borderline_command, find_borderline_usages

    removed_names: list[str] = []
    print()
    print("  Borderline color-marker commands need your input:")
    print()

    for cmd_name, body in sorted(borderline.items()):
        print(f"  \\{cmd_name} defined as: {body}")

        # Show usage excerpts
        excerpts = find_borderline_usages(workdir, main_tex, cmd_name)
        if excerpts:
            print(f"  Usages ({len(excerpts)} shown):")
            for excerpt in excerpts:
                print(f"    {excerpt}")
        else:
            print("  No usages found in document body.")

        try:
            answer = input(f"  Remove \\{cmd_name} and all its usages? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Skipping remaining prompts.")
            break

        if answer in ("y", "yes"):
            count = remove_borderline_command(workdir, main_tex, cmd_name, body)
            removed_names.append(cmd_name)
            print(f"  Removed \\{cmd_name} (definition + {count} invocations)")
        else:
            print(f"  Kept \\{cmd_name}")
        print()

    return removed_names


def _print_summary(summary: dict) -> None:
    """Print the final summary."""
    print()
    print("=" * 40)
    print("  arxivable summary")
    print("=" * 40)
    print(f"  Source:    {summary['source']}")
    print(f"  Output:    {summary['output']} ({format_size(summary['output_size'])})")
    print()

    if summary["comments_stripped"]:
        print(f"  Comments:  Stripped from {len(summary['comments_stripped'])} .tex files")

    ts = summary.get("todo_summary")
    if ts:
        parts = []
        if ts.get("file_removed"):
            parts.append(f"removed {ts['file_removed']}")
        if ts.get("definitions_removed"):
            parts.append(f"{ts['definitions_removed']} definitions")
        if ts.get("invocations_removed"):
            parts.append(f"{ts['invocations_removed']} invocations removed")
        if parts:
            print(f"  Todos:     {', '.join(parts)}")

    if summary["files_removed"]:
        total_removed = len(summary["files_removed"])
        print(f"  Removed:   {total_removed} unused files")
        # Show up to 8 removed files
        for f in summary["files_removed"][:8]:
            print(f"             - {f}")
        if total_removed > 8:
            print(f"             ... and {total_removed - 8} more")

    br = summary.get("borderline_removed")
    if br:
        print(f"  Reviewed:  Removed {len(br)} borderline command(s): "
              + ", ".join(f"\\{n}" for n in br))

    if summary["fixes"]:
        for i, fix in enumerate(summary["fixes"]):
            prefix = "  Fixes:    " if i == 0 else "            "
            print(f"{prefix} {fix}")

    status = "OK" if summary["compile_errors"] == 0 else "ERRORS"
    warn_str = f" ({summary['compile_warnings']} warnings)" if summary["compile_warnings"] else ""
    print(f"  Compile:   {status}{warn_str}")

    if summary.get("claude_verification"):
        print()
        print("-" * 40)
        print("  Claude verification")
        print("-" * 40)
        # Indent each line of the analysis
        for line in summary["claude_verification"].split("\n"):
            print(f"  {line}")

    print()
