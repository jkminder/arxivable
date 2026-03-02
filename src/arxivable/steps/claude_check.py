"""Step: Optional Claude-based verification of all changes."""

from __future__ import annotations

import shutil
import subprocess


REVIEW_PROMPT = """\
You are reviewing automated changes made to a LaTeX paper before arXiv submission.
Your job is to VERIFY that nothing important was incorrectly removed or modified.
Do NOT suggest additional changes — only flag problems with what was done.

Be concise. For each section, say "OK" if everything looks fine, or flag specific issues.

Here is a summary of what was done:
{changes_description}

The working directory is: {workdir}

Run `git diff` in that directory to see the exact changes that were made. Review the diff carefully and flag any concerns:
1. Were any important files incorrectly removed?
2. Were any todo commands incorrectly classified (real content removed as todos)?
3. Did comment stripping accidentally remove real content (non-comment LaTeX)?
4. Are there any important compilation warnings or errors?

If everything looks good, say "All changes look correct."
"""


def _run_claude(
    prompt: str, stdin: str = "", verbose: bool = False, timeout: int = 10*60
) -> str | None:
    """Run claude CLI with a prompt. Returns response or None."""
    if not shutil.which("claude"):
        print("  Warning: 'claude' CLI not found, skipping AI verification")
        print("  Install: https://docs.anthropic.com/en/docs/claude-code")
        return None

    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--model", "opus"],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
        else:
            if verbose:
                print(f"  Claude verification failed: {proc.stderr[:200]}")
            return None
    except subprocess.TimeoutExpired:
        print("  Warning: Claude verification timed out")
        return None
    except Exception as e:
        if verbose:
            print(f"  Claude verification error: {e}")
        return None


def verify_changes(
    workdir: str = "",
    todo_commands: list[str] | None = None,
    todo_invocations_removed: int = 0,
    borderline_commands: dict[str, str] | None = None,
    files_removed: list[str] | None = None,
    comments_stripped: list[str] | None = None,
    compile_warnings: list[str] | None = None,
    compile_errors: list[str] | None = None,
    verbose: bool = False,
) -> str | None:
    """Comprehensive Claude verification of all arxivable changes.

    Returns analysis string or None.
    """
    todo_commands = todo_commands or []
    borderline_commands = borderline_commands or {}
    files_removed = files_removed or []
    comments_stripped = comments_stripped or []
    compile_warnings = compile_warnings or []
    compile_errors = compile_errors or []

    sections = []

    # Todo commands
    if todo_commands:
        sections.append(
            f"TODO COMMANDS REMOVED ({len(todo_commands)} definitions, "
            f"{todo_invocations_removed} invocations):\n"
            + "\n".join(f"  \\{c}" for c in sorted(todo_commands))
        )

    # Borderline color-marker commands
    if borderline_commands:
        sections.append(
            "BORDERLINE COLOR-MARKER COMMANDS (NOT removed, need manual review):\n"
            "These use \\color{{...}} but were defined outside the todo-commands file.\n"
            "Each could be a todo marker that SHOULD be removed, or a semantic styling "
            "command that should be kept:\n"
            + "\n".join(
                f"  \\{name}: {body}" for name, body in borderline_commands.items()
            )
        )

    # Files removed
    if files_removed:
        sections.append(
            f"FILES REMOVED AS UNUSED ({len(files_removed)}):\n"
            + "\n".join(f"  {f}" for f in files_removed[:30])
            + (f"\n  ... and {len(files_removed) - 30} more" if len(files_removed) > 30 else "")
        )

    # Comment stripping
    if comments_stripped:
        sections.append(
            f"COMMENTS STRIPPED from {len(comments_stripped)} files:\n"
            + "\n".join(f"  {f}" for f in comments_stripped)
        )

    # Compilation issues
    if compile_errors:
        sections.append(
            "COMPILATION ERRORS:\n"
            + "\n".join(f"  {e}" for e in compile_errors[:10])
        )
    if compile_warnings:
        # Filter out overfull/underfull warnings
        important = [
            w for w in compile_warnings
            if "Overfull" not in w and "Underfull" not in w
        ]
        if important:
            sections.append(
                "COMPILATION WARNINGS (excluding overfull/underfull):\n"
                + "\n".join(f"  {w}" for w in important[:15])
            )

    if not sections and not workdir:
        return None

    changes_description = "\n\n".join(sections) if sections else "No metadata summary available."
    prompt = REVIEW_PROMPT.format(
        changes_description=changes_description,
        workdir=workdir,
    )
    return _run_claude(prompt, verbose=verbose)
