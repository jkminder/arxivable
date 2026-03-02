"""Click CLI definition for arxivable."""

from __future__ import annotations

import click

from arxivable import __version__
from arxivable.pipeline import run_pipeline


@click.command()
@click.argument("source")
@click.option(
    "-o",
    "--output",
    default=None,
    type=click.Path(),
    help="Output zip path [default: ~/Downloads/<project>_arxiv.zip]",
)
@click.option(
    "-m",
    "--main",
    "main_file",
    default=None,
    help="Main .tex file [default: auto-detect via \\documentclass]",
)
@click.option(
    "--force",
    is_flag=True,
    help="Force-remove active (non-disabled) todo notes instead of crashing",
)
@click.option(
    "-c",
    "--check-with-claude",
    is_flag=True,
    help="Use Claude Code to verify all changes are correct",
)
@click.option(
    "--keep-temp",
    is_flag=True,
    help="Keep temp working directory for debugging",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview what changes would be made without applying them",
)
@click.option("-v", "--verbose", is_flag=True, help="Detailed progress output")
@click.version_option(version=__version__)
def main(
    source: str,
    output: str | None,
    main_file: str | None,
    force: bool,
    check_with_claude: bool,
    keep_temp: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Prepare a LaTeX project for arXiv submission.

    SOURCE is a folder path or git URL.
    """
    run_pipeline(
        source=source,
        output=output,
        main_file=main_file,
        force=force,
        check_with_claude=check_with_claude,
        keep_temp=keep_temp,
        dry_run=dry_run,
        verbose=verbose,
    )
