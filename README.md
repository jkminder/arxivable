# arxivable

Prepare Overleaf LaTeX papers for arXiv submission. One command to strip comments, remove todos, clean unused files, ensure arXiv compatibility, and produce a ready-to-upload zip. 
Optionally, you can enable Claude to review all changes made by the script and verify that nothing important was incorrectly removed.

## Prerequisites

A TeX distribution with `pdflatex` and `bibtex`:

```bash
# macOS
brew install --cask mactex

# Ubuntu/Debian
sudo apt install texlive-full
```

## Installation

```bash
# Install from GitHub
uv tool install git+https://github.com/jkminder/arxivable

# Or install locally for development
git clone https://github.com/jkminder/arxivable
cd arxivable
uv venv && uv pip install -e .
```

## Usage

```bash
# From a local folder
arxivable /path/to/your/project

# From a git URL
arxivable git@github.com:user/paper-repo.git

# With options
arxivable /path/to/project -o output.zip --verbose
arxivable /path/to/project --dry-run          # preview changes
arxivable /path/to/project --force             # force-remove active todos
arxivable /path/to/project -c                  # use Claude to verify all changes
```

## What it does

1. **Checks dependencies** — verifies `pdflatex`, `bibtex`, `git` are installed
2. **Copies to temp dir** — clones git repos or copies folders, never modifies originals
3. **Cleans junk files** — removes `.git/`, `.DS_Store`, build artifacts, etc.
4. **Removes todo infrastructure** — discovers all `todonotes`-based commands via BFS, removes definitions and invocations. Crashes on active (non-disabled) todos unless `--force`. Interactively prompts about borderline color-marker commands (e.g. `\shared`) that may or may not be todos
5. **Strips comments** — removes `%` comments from body `.tex` files (preserves preamble files where `%` is used for macro line continuation)
6. **Removes unused files** — detects referenced files via `\includegraphics`, `\input`, `\bibliography`, `\lstinputlisting`, custom macros, etc. Removes everything else
7. **Applies arXiv fixes** — adds `\pdfoutput=1` (pdflatex only), generates `.bbl` if missing, detects XeLaTeX/LuaLaTeX requirements
8. **Compiles & verifies** — runs full `pdflatex`/`bibtex` (or `xelatex`/`lualatex`) cycle, reports errors/warnings
9. **Creates zip** — clean archive ready for arXiv upload

## Options

```
arxivable <source> [options]

source              Folder path or git URL

Options:
  -o, --output PATH       Output zip path [default: ~/Downloads/<project>_arxiv.zip]
  -m, --main FILE         Main .tex file [default: auto-detect via \documentclass]
  --force                 Force-remove active (non-disabled) todos
  -c, --check-with-claude Use Claude Code to verify all changes are correct
  --keep-temp             Keep temp working directory for debugging
  --dry-run               Preview changes without applying them
  -v, --verbose           Detailed progress output
  --version / --help
```
