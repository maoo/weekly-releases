from __future__ import annotations

import html
from datetime import date
from itertools import groupby
from pathlib import Path

from weekly_releases.models import Release
from weekly_releases.timebox import OutputFormat, iso_week_file

_HTML_STYLES = """
:root {
  color-scheme: light;
  --bg: #f4f6f9;
  --surface: #ffffff;
  --text: #1e293b;
  --muted: #64748b;
  --border: #e2e8f0;
  --accent: #2563eb;
  --accent-soft: #eff6ff;
  --radius: 10px;
  --shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 1.5rem clamp(1rem, 4vw, 2.5rem) 3rem;
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto,
    "Helvetica Neue", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  color: var(--text);
  background: linear-gradient(165deg, #eef2ff 0%, var(--bg) 38%, var(--bg) 100%);
  min-height: 100vh;
}
.wrap {
  max-width: 52rem;
  margin: 0 auto;
}
header {
  margin-bottom: 1.75rem;
}
header h1 {
  margin: 0 0 0.35rem;
  font-size: clamp(1.35rem, 3vw, 1.75rem);
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #0f172a;
}
header p {
  margin: 0;
  color: var(--muted);
  font-size: 0.95rem;
}
.projects {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}
details.project {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}
details.project > summary {
  cursor: pointer;
  list-style: none;
  padding: 0.85rem 1.1rem;
  font-weight: 600;
  font-size: 1rem;
  color: #0f172a;
  background: linear-gradient(to bottom, #fafbff, #f1f5f9);
  border-bottom: 1px solid transparent;
  user-select: none;
}
details.project > summary::-webkit-details-marker { display: none; }
details.project > summary::marker { content: ""; }
details.project[open] > summary {
  border-bottom-color: var(--border);
  background: var(--accent-soft);
}
details.project > summary:hover {
  background: #e8eef7;
}
details.project[open] > summary:hover {
  background: #e0eafc;
}
.summary-count {
  font-weight: 500;
  color: var(--muted);
  font-size: 0.9em;
}
.releases {
  margin: 0;
  padding: 0.5rem 0 0.25rem;
  list-style: none;
}
.release {
  padding: 0.85rem 1.1rem 1rem;
  border-bottom: 1px solid #f1f5f9;
}
.release:last-child { border-bottom: none; }
.release-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.65rem;
  align-items: baseline;
  font-size: 0.92rem;
  color: var(--text);
}
.release-meta .sep { color: var(--border); user-select: none; }
.mono {
  font-family: ui-monospace, "Cascadia Code", "SF Mono", Menlo, Consolas, monospace;
  font-size: 0.84em;
  background: #f8fafc;
  padding: 0.12em 0.35em;
  border-radius: 4px;
  border: 1px solid #e8ecf1;
}
.source-tag {
  text-transform: lowercase;
  font-size: 0.8rem;
  color: var(--muted);
}
a.link {
  color: var(--accent);
  text-decoration: none;
  font-weight: 500;
}
a.link:hover { text-decoration: underline; }
.description {
  margin: 0.55rem 0 0;
  padding-left: 0.75rem;
  font-size: 0.88rem;
  color: var(--muted);
  border-left: 3px solid #cbd5e1;
  white-space: pre-wrap;
  word-break: break-word;
}
.empty {
  padding: 2rem 1.25rem;
  text-align: center;
  color: var(--muted);
  background: var(--surface);
  border-radius: var(--radius);
  border: 1px dashed var(--border);
}
"""


def _release_li_html(rel: Release) -> str:
    date_value = html.escape(rel.released_at.date().isoformat())
    gh = html.escape(rel.github_repo) if rel.github_repo else "—"
    artifact = html.escape(rel.artifact)
    version = html.escape(rel.version)
    source = html.escape(rel.source)
    url_esc = html.escape(rel.url, quote=True)
    parts = [
        f'<span class="mono">{gh}</span>',
        '<span class="sep">|</span>',
        f'<span class="source-tag">{source}</span>',
        '<span class="sep">|</span>',
        f'<span class="mono">{artifact}</span>',
        '<span class="sep">|</span>',
        f'<span class="mono">{version}</span>',
        '<span class="sep">|</span>',
        f"<span>{date_value}</span>",
        '<span class="sep">|</span>',
        f'<a class="link" href="{url_esc}">link</a>',
    ]
    meta = f'<div class="release-meta">{"".join(parts)}</div>'
    desc_block = ""
    if rel.description:
        body = html.escape(rel.description).replace("\n", "<br>\n")
        desc_block = f'<p class="description">{body}</p>'
    return f'<li class="release">{meta}{desc_block}</li>'


def render_html(target_date: date, releases: list[Release]) -> str:
    iso = target_date.isocalendar()
    title = f"FINOS releases for {iso.year} week {iso.week:02d}"
    title_esc = html.escape(title)

    if not releases:
        body_inner = '<p class="empty">No releases found in this period.</p>'
    else:
        blocks: list[str] = []
        ordered = sorted(
            releases, key=lambda r: (r.project.lower(), r.project, r.released_at)
        )
        for project, group in groupby(ordered, key=lambda r: r.project):
            group_list = list(group)
            n = len(group_list)
            proj_esc = html.escape(project)
            lis = "\n".join(_release_li_html(r) for r in group_list)
            blocks.append(
                f'<details class="project">\n'
                f"<summary>{proj_esc}"
                f'<span class="summary-count"> ({n})</span></summary>\n'
                f'<ul class="releases">\n{lis}\n</ul>\n'
                f"</details>"
            )
        body_inner = f'<div class="projects">\n{"".join(blocks)}\n</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_esc}</title>
<style>
{_HTML_STYLES}
</style>
</head>
<body>
<div class="wrap">
<header>
<h1>{title_esc}</h1>
<p>FINOS community releases (UTC), grouped by project.</p>
</header>
<main>
{body_inner}
</main>
</div>
</body>
</html>
"""


def render_markdown(target_date: date, releases: list[Release]) -> str:
    iso = target_date.isocalendar()
    lines = [f"# FINOS releases for {iso.year} week {iso.week:02d}", ""]
    if not releases:
        lines.append("_No releases found in this period._")
    else:
        ordered = sorted(
            releases, key=lambda r: (r.project.lower(), r.project, r.released_at)
        )
        for project, group in groupby(ordered, key=lambda r: r.project):
            lines.append("")
            lines.append("<details>")
            lines.append(f"<summary>{html.escape(project)}</summary>")
            lines.append("")
            for rel in group:
                lines.append(rel.as_markdown_line(omit_project=True))
            lines.append("")
            lines.append("</details>")
    lines.append("")
    return "\n".join(lines)


def render_weekly(
    target_date: date, releases: list[Release], *, output_format: OutputFormat
) -> str:
    if output_format == "html":
        return render_html(target_date, releases)
    return render_markdown(target_date, releases)


def write_weekly_file(
    base_dir: Path,
    target_date: date,
    releases: list[Release],
    *,
    output_format: OutputFormat = "html",
) -> Path:
    path = iso_week_file(base_dir, target_date, output_format=output_format)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_weekly(target_date, releases, output_format=output_format),
        encoding="utf-8",
    )
    return path


_INDEX_STYLES = """
:root {
  color-scheme: light;
  --bg: #f4f6f9;
  --surface: #ffffff;
  --text: #1e293b;
  --muted: #64748b;
  --border: #e2e8f0;
  --accent: #2563eb;
  --radius: 10px;
  --shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 1.5rem clamp(1rem, 4vw, 2.5rem) 3rem;
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto,
    "Helvetica Neue", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  color: var(--text);
  background: linear-gradient(165deg, #eef2ff 0%, var(--bg) 38%, var(--bg) 100%);
  min-height: 100vh;
}
.wrap { max-width: 52rem; margin: 0 auto; }
header { margin-bottom: 1.75rem; }
header h1 {
  margin: 0 0 0.35rem;
  font-size: clamp(1.35rem, 3vw, 1.75rem);
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #0f172a;
}
header p { margin: 0; color: var(--muted); font-size: 0.95rem; }
.year-block {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 1rem 1.15rem 1.15rem;
  margin-bottom: 1rem;
}
.year-block h2 {
  margin: 0 0 0.75rem;
  font-size: 1.1rem;
  font-weight: 650;
  color: #0f172a;
}
.week-links {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 0.65rem;
}
.week-links a {
  display: inline-block;
  padding: 0.35rem 0.65rem;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: #f8fafc;
  color: var(--accent);
  text-decoration: none;
  font-weight: 500;
  font-size: 0.92rem;
}
.week-links a:hover {
  border-color: var(--accent);
  background: #eff6ff;
}
.empty-year {
  margin: 0;
  color: var(--muted);
  font-size: 0.92rem;
}
"""


def collect_year_week_html_files(base_dir: Path) -> list[tuple[int, list[int]]]:
    """Numeric year subdirectories under ``base_dir``, each with sorted week stems from ``WW.html``."""
    if not base_dir.exists():
        return []
    years: list[int] = []
    for child in base_dir.iterdir():
        if child.is_dir() and child.name.isdigit():
            years.append(int(child.name))
    years.sort()
    rows: list[tuple[int, list[int]]] = []
    for y in years:
        ydir = base_dir / str(y)
        weeks = sorted(
            int(p.stem)
            for p in ydir.iterdir()
            if p.is_file() and p.suffix == ".html" and p.stem.isdigit()
        )
        rows.append((y, weeks))
    return rows


def render_releases_index_html(base_dir: Path) -> str:
    """Standalone HTML listing each year folder and links to ``WW.html`` week reports."""
    rows = collect_year_week_html_files(base_dir)
    title = "FINOS weekly releases"
    title_esc = html.escape(title)
    if not rows:
        main_inner = (
            '<p class="empty-year">No year folders or HTML week reports yet.</p>'
        )
    else:
        sections: list[str] = []
        for year, weeks in rows:
            y_esc = html.escape(str(year))
            if weeks:
                lis = []
                for w in weeks:
                    href = html.escape(f"{year}/{w:02d}.html", quote=True)
                    label = html.escape(f"Week {w:02d}")
                    lis.append(f'<li><a href="{href}">{label}</a></li>')
                ul = f'<ul class="week-links">\n{"".join(lis)}\n</ul>'
            else:
                ul = '<p class="empty-year">No HTML week reports for this year.</p>'
            sections.append(
                f'<section class="year-block">\n<h2>{y_esc}</h2>\n{ul}\n</section>'
            )
        main_inner = "\n".join(sections)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_esc}</title>
<style>
{_INDEX_STYLES}
</style>
</head>
<body>
<div class="wrap">
<header>
<h1>{title_esc}</h1>
<p>Browse reports by ISO calendar year and week (<code>YYYY/WW.html</code>).</p>
</header>
<main>
{main_inner}
</main>
</div>
</body>
</html>
"""


def write_releases_index(base_dir: Path) -> Path:
    """Write ``base_dir/index.html`` listing year subfolders and week HTML pages."""
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / "index.html"
    path.write_text(render_releases_index_html(base_dir), encoding="utf-8")
    return path


def latest_weekly_file(base_dir: Path) -> Path | None:
    if not base_dir.exists():
        return None
    years = sorted([d for d in base_dir.iterdir() if d.is_dir() and d.name.isdigit()])
    if not years:
        return None
    latest_year = years[-1]
    candidates = [
        p
        for p in latest_year.iterdir()
        if p.suffix in (".md", ".html") and p.stem.isdigit()
    ]
    if not candidates:
        return None

    def sort_key(p: Path) -> tuple[int, int]:
        week = int(p.stem)
        fmt_rank = 1 if p.suffix == ".html" else 0
        return week, fmt_rank

    return max(candidates, key=sort_key)
