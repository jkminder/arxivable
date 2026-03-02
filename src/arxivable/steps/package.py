"""Step: Clean build artifacts and create final zip."""

from __future__ import annotations

import os
import zipfile

from arxivable.utils import format_size

# Build artifacts to remove (keep .bbl!)
# These are only removed from the project ROOT, not subdirectories
ARTIFACT_EXTENSIONS = {
    ".app",
    ".aux",
    ".log",
    ".out",
    ".synctex.gz",
    ".blg",
    ".brf",
    ".fls",
    ".fdb_latexmk",
    ".toc",
    ".lof",
    ".lot",
    ".loc",
    ".soc",
    ".nav",
    ".snm",
    ".vrb",
    ".bcf",
    ".run.xml",
    ".xdv",
}


def clean_build_artifacts(
    workdir: str, main_tex: str, verbose: bool = False
) -> int:
    """Remove build artifacts. Returns count of removed files.

    Only removes the compiled PDF matching main_tex, plus auxiliary files
    from any directory (aux/log/etc are never real content).
    """
    count = 0
    main_base = os.path.splitext(main_tex)[0]

    for root, _dirs, files in os.walk(workdir):
        for fname in files:
            base, ext = os.path.splitext(fname)
            fpath = os.path.join(root, fname)

            # Remove the compiled PDF only for the main document (in root)
            if ext == ".pdf" and root == workdir and base == main_base:
                os.remove(fpath)
                count += 1
                if verbose:
                    print(f"  Removed artifact: {os.path.relpath(fpath, workdir)}")
                continue

            # Remove standard LaTeX auxiliary files from anywhere
            if ext in ARTIFACT_EXTENSIONS:
                os.remove(fpath)
                count += 1
                if verbose:
                    print(f"  Removed artifact: {os.path.relpath(fpath, workdir)}")

    # Remove empty directories left behind
    for root, dirs, files in os.walk(workdir, topdown=False):
        if root == workdir:
            continue
        if not os.listdir(root):
            os.rmdir(root)

    return count


def create_zip(workdir: str, output_path: str, verbose: bool = False) -> int:
    """Create zip from workdir contents. Returns total size in bytes."""
    output_path = os.path.expanduser(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    total_size = 0
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(workdir):
            for fname in files:
                fpath = os.path.join(root, fname)
                arcname = os.path.relpath(fpath, workdir)
                zf.write(fpath, arcname)
                total_size += os.path.getsize(fpath)
                if verbose:
                    print(f"  Added: {arcname}")

    zip_size = os.path.getsize(output_path)
    if verbose:
        print(f"  Zip size: {format_size(zip_size)}")
    return zip_size
