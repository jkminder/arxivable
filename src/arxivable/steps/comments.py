"""Step: Remove comments from .tex files.

Only strips comments after \\begin{document} in the main file and in
non-preamble .tex files.  Preamble files (those \\input-ed before
\\begin{document}) are left untouched because % at end-of-line in
\\newcommand definitions prevents unwanted whitespace.
"""

from __future__ import annotations

import os
import re


# Environments where % is literal, not a comment
VERBATIM_ENVS = {"verbatim", "lstlisting", "minted", "comment"}

_VERB_PATTERN = re.compile(r"\\verb(.)")


def find_preamble_inputs(main_tex_path: str) -> set[str]:
    """Return set of absolute paths to files \\input-ed before \\begin{document}."""
    base_dir = os.path.dirname(main_tex_path)
    preamble_files: set[str] = set()
    with open(main_tex_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if r"\begin{document}" in line:
                break
            m = re.search(r"\\input\{([^}]+)\}", line)
            if m:
                path = m.group(1)
                if not path.endswith(".tex"):
                    path += ".tex"
                abs_path = os.path.normpath(os.path.join(base_dir, path))
                preamble_files.add(abs_path)
    return preamble_files


def _is_escaped_percent(line: str, idx: int) -> bool:
    """Check if % at idx is escaped by counting preceding backslashes."""
    n_backslashes = 0
    i = idx - 1
    while i >= 0 and line[i] == "\\":
        n_backslashes += 1
        i -= 1
    return n_backslashes % 2 == 1


def _find_comment_start(line: str) -> int | None:
    """Find position of first unescaped % that is not inside \\verb.

    Returns None if no comment found.
    """
    i = 0
    while i < len(line):
        # Check for \verb with arbitrary delimiter
        m = _VERB_PATTERN.match(line, i)
        if m:
            delim = m.group(1)
            end = line.find(delim, m.end())
            if end == -1:
                return None  # unterminated \verb, don't strip
            i = end + 1
            continue
        if line[i] == "%" and not _is_escaped_percent(line, i):
            return i
        i += 1
    return None


def strip_comments_from_content(text: str) -> str:
    """Strip comments from .tex content (body only)."""
    lines = text.split("\n")
    result: list[str] = []
    in_verbatim = False
    verbatim_env_name = ""
    prev_blank = False

    for line in lines:
        # Track verbatim environments
        if not in_verbatim:
            for env in VERBATIM_ENVS:
                if re.search(rf"\\begin\{{{env}\}}", line):
                    in_verbatim = True
                    verbatim_env_name = env
                    break
        elif re.search(rf"\\end\{{{verbatim_env_name}\}}", line):
            in_verbatim = False
            result.append(line)
            prev_blank = False
            continue

        if in_verbatim:
            result.append(line)
            prev_blank = False
            continue

        # Find and strip comment
        pos = _find_comment_start(line)
        if pos is not None:
            stripped = line[:pos].rstrip()
            if not stripped:
                # Comment-only line → skip entirely
                continue
            line = stripped

        # Collapse consecutive blank lines
        if line.strip() == "":
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False

        result.append(line)

    return "\n".join(result)


def strip_comments_from_file(filepath: str) -> bool:
    """Strip comments from a single .tex file. Returns True if modified."""
    with open(filepath, encoding="utf-8", errors="replace") as f:
        original = f.read()

    new_content = strip_comments_from_content(original)

    if new_content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    return False


def strip_body_comments_main(main_tex_path: str) -> bool:
    """Strip comments only after \\begin{document} in main .tex file."""
    with open(main_tex_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Find \begin{document}
    m = re.search(r"\\begin\{document\}", content)
    if not m:
        return False

    preamble = content[: m.end()]
    body = content[m.end() :]

    new_body = strip_comments_from_content(body)
    if new_body != body:
        with open(main_tex_path, "w", encoding="utf-8") as f:
            f.write(preamble + new_body)
        return True
    return False


def run_strip_comments(
    workdir: str, main_tex: str, verbose: bool = False, dry_run: bool = False
) -> list[str]:
    """Strip comments from all eligible .tex files. Returns list of modified files."""
    main_path = os.path.join(workdir, main_tex)
    preamble_files = find_preamble_inputs(main_path)

    modified: list[str] = []

    # Collect all .tex files
    for root, _dirs, files in os.walk(workdir):
        for fname in files:
            if not fname.endswith(".tex"):
                continue
            fpath = os.path.join(root, fname)

            # Skip preamble files
            if os.path.normpath(fpath) in preamble_files:
                if verbose:
                    print(f"  Skipping preamble file: {os.path.relpath(fpath, workdir)}")
                continue

            # Skip .sty/.cls/.bst (already excluded by .tex filter, but be safe)
            if fpath == main_path:
                if dry_run:
                    modified.append(os.path.relpath(fpath, workdir))
                    continue
                if strip_body_comments_main(fpath):
                    modified.append(os.path.relpath(fpath, workdir))
                    if verbose:
                        print(f"  Stripped comments: {os.path.relpath(fpath, workdir)}")
            else:
                if dry_run:
                    modified.append(os.path.relpath(fpath, workdir))
                    continue
                if strip_comments_from_file(fpath):
                    modified.append(os.path.relpath(fpath, workdir))
                    if verbose:
                        print(f"  Stripped comments: {os.path.relpath(fpath, workdir)}")

    return modified
