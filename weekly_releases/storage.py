from __future__ import annotations

from datetime import date
from itertools import groupby
from pathlib import Path

from weekly_releases.models import Release
from weekly_releases.timebox import iso_week_file


def render_markdown(target_date: date, releases: list[Release]) -> str:
    iso = target_date.isocalendar()
    lines = [f"# FINOS releases for {iso.year} week {iso.week:02d}", ""]
    if not releases:
        lines.append("_No releases found in this period._")
    else:
        ordered = sorted(releases, key=lambda r: (r.project.lower(), r.project, r.released_at))
        for project, group in groupby(ordered, key=lambda r: r.project):
            lines.append(f"## {project}")
            lines.append("")
            for rel in group:
                lines.append(rel.as_markdown_line(omit_project=True))
            lines.append("")
    lines.append("")
    return "\n".join(lines)


def write_weekly_file(base_dir: Path, target_date: date, releases: list[Release]) -> Path:
    path = iso_week_file(base_dir, target_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(target_date, releases), encoding="utf-8")
    return path


def latest_weekly_file(base_dir: Path) -> Path | None:
    if not base_dir.exists():
        return None
    years = sorted([d for d in base_dir.iterdir() if d.is_dir() and d.name.isdigit()])
    if not years:
        return None
    latest_year = years[-1]
    files = sorted(latest_year.glob("*.md"))
    return files[-1] if files else None

