"""Step: Detect and remove unreferenced files."""

from __future__ import annotations

import os
import re


# File-reference patterns
_INCLUDEGRAPHICS = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_INPUT_INCLUDE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
_BIBLIOGRAPHY = re.compile(r"\\(?:bibliography|addbibresource)\s*\{([^}]+)\}")
_BIBSTYLE = re.compile(r"\\bibliographystyle\s*\{([^}]+)\}")
_LSTINPUTLISTING = re.compile(r"\\lstinputlisting\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_USEPACKAGE = re.compile(r"\\usepackage\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_DOCUMENTCLASS = re.compile(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_REQUIRE_PACKAGE = re.compile(r"\\RequirePackage\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_GRAPHICSPATH = re.compile(r"\\graphicspath\s*\{\{([^}]*)\}")
_GRAPHICSPATH_MULTI = re.compile(r"\\graphicspath\s*\{((?:\{[^}]*\})+)\}")

# Custom macro wrappers that reference files (found by scanning definitions)
_CUSTOM_FILE_MACROS: list[re.Pattern] = []

IMAGE_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg")


def _parse_graphicspath(workdir: str) -> list[str]:
    """Parse \\graphicspath from all .tex files. Returns list of directories."""
    paths: list[str] = []
    for root, _dirs, files in os.walk(workdir):
        for fname in files:
            if not fname.endswith(".tex"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, encoding="utf-8", errors="replace") as f:
                content = f.read()
            m = _GRAPHICSPATH_MULTI.search(content)
            if m:
                raw = m.group(1)
                for dm in re.finditer(r"\{([^}]*)\}", raw):
                    paths.append(dm.group(1))
    return paths


def _find_wrapper_macros(workdir: str) -> dict[str, re.Pattern]:
    """Find custom macros that wrap \\includegraphics etc."""
    wrappers: dict[str, re.Pattern] = {}
    file_cmds = {"includegraphics", "input", "include", "lstinputlisting"}

    for root, _dirs, files in os.walk(workdir):
        for fname in files:
            if not fname.endswith(".tex"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Find \newcommand\foo... that contain \includegraphics etc
            for m in re.finditer(
                r"\\(?:newcommand|renewcommand|DeclareRobustCommand)\s*\{?\s*\\(\w+)\}?",
                content,
            ):
                cmd_name = m.group(1)
                # Get the body
                brace_start = content.find("{", m.end())
                if brace_start == -1:
                    continue
                depth = 0
                i = brace_start
                body_start = brace_start
                while i < len(content):
                    if content[i] == "{":
                        depth += 1
                    elif content[i] == "}":
                        depth -= 1
                        if depth == 0:
                            body = content[body_start + 1 : i]
                            break
                    i += 1
                else:
                    continue

                for fc in file_cmds:
                    if f"\\{fc}" in body:
                        # This macro wraps a file-referencing command
                        # Create pattern to extract file arg (first {})
                        wrappers[cmd_name] = re.compile(
                            rf"\\{re.escape(cmd_name)}\s*(?:\[[^\]]*\])?\s*\{{([^}}]+)\}}"
                        )
                        break

    return wrappers


def _resolve_path(ref: str, workdir: str, graphics_paths: list[str]) -> str | None:
    """Resolve a file reference to an actual file on disk."""
    # Try as-is first
    candidate = os.path.join(workdir, ref)
    if os.path.isfile(candidate):
        return os.path.relpath(candidate, workdir)

    # Try with common extensions
    _, ext = os.path.splitext(ref)
    if not ext:
        for try_ext in IMAGE_EXTENSIONS:
            candidate = os.path.join(workdir, ref + try_ext)
            if os.path.isfile(candidate):
                return os.path.relpath(candidate, workdir)

    # Try with .tex extension
    if not ext:
        candidate = os.path.join(workdir, ref + ".tex")
        if os.path.isfile(candidate):
            return os.path.relpath(candidate, workdir)

    # Try with graphicspath
    for gpath in graphics_paths:
        candidate = os.path.join(workdir, gpath, ref)
        if os.path.isfile(candidate):
            return os.path.relpath(candidate, workdir)
        if not ext:
            for try_ext in IMAGE_EXTENSIONS:
                candidate = os.path.join(workdir, gpath, ref + try_ext)
                if os.path.isfile(candidate):
                    return os.path.relpath(candidate, workdir)

    return None


def find_referenced_files(workdir: str, verbose: bool = False) -> set[str]:
    """Find all files referenced from .tex files.

    Returns set of relative paths (from workdir).
    """
    referenced: set[str] = set()
    graphics_paths = _parse_graphicspath(workdir)
    wrapper_macros = _find_wrapper_macros(workdir)

    # Also scan .sty files for \RequirePackage
    sty_packages: set[str] = set()

    for root, _dirs, files in os.walk(workdir):
        for fname in files:
            if not (fname.endswith(".tex") or fname.endswith(".sty")):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, encoding="utf-8", errors="replace") as f:
                raw_content = f.read()

            # For .tex files, strip commented-out lines before scanning for references
            if fname.endswith(".tex"):
                content = "\n".join(
                    line for line in raw_content.split("\n")
                    if not line.lstrip().startswith("%")
                )
            else:
                content = raw_content

            # Track what this file's directory is relative to workdir
            file_dir = os.path.relpath(root, workdir)

            # \includegraphics and custom wrappers
            for m in _INCLUDEGRAPHICS.finditer(content):
                ref = m.group(1).strip()
                # Skip LaTeX parameter references like #1, #2
                if ref.startswith("#"):
                    continue
                resolved = _resolve_path(ref, workdir, graphics_paths)
                if resolved:
                    referenced.add(resolved)
                elif verbose:
                    print(f"  Warning: unresolved reference: {ref} in {os.path.relpath(fpath, workdir)}")

            # \input / \include
            for m in _INPUT_INCLUDE.finditer(content):
                ref = m.group(1).strip()
                resolved = _resolve_path(ref, workdir, graphics_paths)
                if resolved:
                    referenced.add(resolved)

            # \bibliography / \addbibresource
            for m in _BIBLIOGRAPHY.finditer(content):
                refs = m.group(1).strip()
                for ref in refs.split(","):
                    ref = ref.strip()
                    if not ref:
                        continue
                    resolved = _resolve_path(ref, workdir, [])
                    if resolved:
                        referenced.add(resolved)
                    # Try with .bib extension
                    if not ref.endswith(".bib"):
                        resolved = _resolve_path(ref + ".bib", workdir, [])
                        if resolved:
                            referenced.add(resolved)

            # \bibliographystyle
            for m in _BIBSTYLE.finditer(content):
                style = m.group(1).strip()
                # Check for local .bst file
                bst_path = os.path.join(workdir, style + ".bst")
                if os.path.isfile(bst_path):
                    referenced.add(style + ".bst")

            # \lstinputlisting
            for m in _LSTINPUTLISTING.finditer(content):
                ref = m.group(1).strip()
                resolved = _resolve_path(ref, workdir, [])
                if resolved:
                    referenced.add(resolved)

            # \usepackage — check for local .sty files
            for m in _USEPACKAGE.finditer(content):
                pkgs = m.group(1).strip()
                for pkg in pkgs.split(","):
                    pkg = pkg.strip()
                    if not pkg:
                        continue
                    sty_path = os.path.join(workdir, pkg + ".sty")
                    if os.path.isfile(sty_path):
                        referenced.add(pkg + ".sty")

            # \documentclass — check for local .cls file
            for m in _DOCUMENTCLASS.finditer(content):
                cls_name = m.group(1).strip()
                cls_path = os.path.join(workdir, cls_name + ".cls")
                if os.path.isfile(cls_path):
                    referenced.add(cls_name + ".cls")

            # \RequirePackage in .sty files
            if fname.endswith(".sty"):
                for m in _REQUIRE_PACKAGE.finditer(content):
                    pkgs = m.group(1).strip()
                    for pkg in pkgs.split(","):
                        pkg = pkg.strip()
                        if pkg:
                            sty_packages.add(pkg)

            # Custom wrapper macros (e.g. \promptlisting)
            for macro_name, pattern in wrapper_macros.items():
                for m in pattern.finditer(content):
                    ref = m.group(1).strip()
                    resolved = _resolve_path(ref, workdir, [])
                    if resolved:
                        referenced.add(resolved)

    # Resolve \RequirePackage references to local .sty files
    for pkg in sty_packages:
        sty_path = os.path.join(workdir, pkg + ".sty")
        if os.path.isfile(sty_path):
            referenced.add(pkg + ".sty")

    return referenced


def find_all_files(workdir: str) -> set[str]:
    """List all files in workdir as relative paths."""
    all_files: set[str] = set()
    for root, dirs, files in os.walk(workdir):
        # Skip .git directory (may exist as baseline for claude check diffing)
        dirs[:] = [d for d in dirs if d != ".git"]
        for fname in files:
            fpath = os.path.join(root, fname)
            all_files.add(os.path.relpath(fpath, workdir))
    return all_files


def remove_unused_files(
    workdir: str, main_tex: str, verbose: bool = False, dry_run: bool = False
) -> list[str]:
    """Detect and remove unreferenced files. Returns list of removed relative paths."""
    referenced = find_referenced_files(workdir, verbose)

    # Always keep: main .tex file, .bbl files, all .tex files that are \input-ed
    # The main tex file itself
    referenced.add(main_tex)

    # Keep all .bbl files (needed by arXiv)
    for root, _dirs, files in os.walk(workdir):
        for fname in files:
            if fname.endswith(".bbl"):
                referenced.add(os.path.relpath(os.path.join(root, fname), workdir))

    all_files = find_all_files(workdir)
    unused = all_files - referenced

    # Don't remove .tex files that are directly \input-ed (they're already tracked)
    # But DO remove .tex files that are genuinely unused

    removed: list[str] = []
    for rel_path in sorted(unused):
        fpath = os.path.join(workdir, rel_path)
        if verbose:
            print(f"  Removing unused: {rel_path}")
        if not dry_run:
            os.remove(fpath)
        removed.append(rel_path)

    # Remove empty directories
    if not dry_run:
        for root, dirs, files in os.walk(workdir, topdown=False):
            if root == workdir:
                continue
            if not os.listdir(root):
                os.rmdir(root)
                if verbose:
                    print(f"  Removed empty dir: {os.path.relpath(root, workdir)}/")

    return removed
