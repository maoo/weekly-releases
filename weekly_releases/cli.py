from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast

import typer

from weekly_releases.runner import run
from weekly_releases.timebox import OutputFormat

app = typer.Typer(
    help="Scan FINOS package repositories and produce weekly release reports (HTML or markdown)."
)


@app.command()
def scan(
    output_dir: Path = typer.Option(Path("docs"), "--output-dir", "-o"),
    today: str | None = typer.Option(
        None, help="Override current date in ISO format (YYYY-MM-DD)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Run scan without writing files."
    ),
    current_week: bool = typer.Option(
        False,
        "--current-week",
        help=(
            "Crawl only the ISO week containing --today (or today) and write that week's "
            "report file (--format); skips epoch-based backfill."
        ),
    ),
    quiet: bool = typer.Option(
        False, "--quiet", help="Only print final result output."
    ),
    landscape_source: str | None = typer.Option(
        None, help="Optional local file path or URL for landscape YAML."
    ),
    output_format: str = typer.Option(
        "html",
        "--format",
        help='Output file format: "html" (standalone page, default) or "md" (markdown).',
    ),
) -> None:
    run_date = date.fromisoformat(today) if today else date.today()
    fmt = output_format.strip().lower()
    if fmt not in ("html", "md"):
        typer.echo('Error: --format must be "html" or "md".', err=True)
        raise typer.Exit(code=1)
    fmt_out: OutputFormat = cast(OutputFormat, fmt)

    def progress(message: str) -> None:
        if not quiet:
            typer.echo(f"[progress] {message}")

    result = run(
        output_dir=output_dir,
        today=run_date,
        dry_run=dry_run,
        landscape_source=landscape_source,
        progress=progress,
        current_week_only=current_week and not dry_run,
        output_format=fmt_out,
    )
    if dry_run:
        typer.echo(
            f"Dry run: collected {len(result.releases)} releases for the current week"
        )
        for rel in sorted(result.releases, key=lambda r: r.released_at):
            typer.echo(rel.as_markdown_line())
        return

    if current_week:
        typer.echo(
            "Current week: wrote "
            f"{len(result.releases)} releases to {result.output_files[0]}"
        )
        return

    if not result.output_files:
        typer.echo("No missing weeks; nothing written.")
        return

    typer.echo(
        f"Wrote {len(result.releases)} releases across "
        f"{len(result.output_files)} week(s):"
    )
    for path in result.output_files:
        typer.echo(f"- {path}")


if __name__ == "__main__":
    app()
