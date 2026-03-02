"""Step: Prepare working directory (git clone or folder copy)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

from arxivable.utils import is_git_url


def prepare_workdir(source: str, verbose: bool = False) -> tuple[str, str]:
    """Clone or copy source into a temp directory.

    Returns (workdir_path, project_name).
    """
    workdir = tempfile.mkdtemp(prefix="arxivable_")

    if is_git_url(source):
        if verbose:
            print(f"  Cloning {source} ...")
        project_name = os.path.basename(source.rstrip("/")).removesuffix(".git")
        clone_dest = os.path.join(workdir, project_name)
        subprocess.run(
            ["git", "clone", "--depth", "1", source, clone_dest],
            capture_output=not verbose,
            check=True,
        )
        return clone_dest, project_name
    else:
        source = os.path.abspath(os.path.expanduser(source))
        if not os.path.isdir(source):
            shutil.rmtree(workdir)
            print(f"Error: source directory not found: {source}")
            sys.exit(1)
        project_name = os.path.basename(source.rstrip("/"))
        dest = os.path.join(workdir, project_name)
        if verbose:
            print(f"  Copying {source} ...")
        shutil.copytree(source, dest, symlinks=False)
        return dest, project_name
