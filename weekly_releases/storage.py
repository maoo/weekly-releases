from __future__ import annotations

import html
import re
from datetime import date
from itertools import groupby
from pathlib import Path

from weekly_releases.grouping import (
    ReleaseGroup,
    cluster_releases,
    displayed_artifacts,
    render_group_markdown,
    select_highlight_groups,
)
from weekly_releases.models import Release
from weekly_releases.timebox import OutputFormat, iso_week_file

# Index lists only on-disk ISO week-year folders from this year onward (project epoch).
_INDEX_EPOCH_ISO_YEAR = 2026
_MONTH_NAMES_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

# Monthly rollup pages live next to ``WW.html`` under the ISO week-year folder.
_WEEKLY_PROJECT_BLOCK_RE = re.compile(
    r'<details class="project">\s*'
    r"<summary>(?P<summary>.*?)</summary>\s*"
    r'<ul class="releases">\s*(?P<ulbody>.*?)\s*</ul>\s*</details>',
    re.DOTALL | re.IGNORECASE,
)
# Outer ``<li class="release">`` (singleton or grouped) — tolerates extra
# attributes such as ``data-sort-date``. Sub-items inside grouped rows use
# ``<div class="group-artifact">`` (not ``<li>``) so this non-greedy match still
# closes at the correct outer ``</li>``. The explicit closing ``"`` after
# ``release`` prevents accidental matches against ``class="release-foo"``.
_RELEASE_LI_RE = re.compile(
    r'<li class="release"[^>]*>.*?</li>',
    re.DOTALL | re.IGNORECASE,
)
_SUMMARY_COUNT_SPAN_RE = re.compile(
    r'<span class="summary-count">\s*\([^)]*\)\s*</span>',
    re.IGNORECASE | re.DOTALL,
)
# Preferred sort key for each ``<li class="release">``: the explicit
# ``data-sort-date="YYYY-MM-DD"`` attribute (= earliest underlying release date).
_RELEASE_LI_DATA_SORT_RE = re.compile(
    r'<li class="release"[^>]*\sdata-sort-date="(\d{4}-\d{2}-\d{2})"',
    re.IGNORECASE,
)
# Highlight marker on a ``<li class="release">`` row (``"major"`` or ``"minor"``).
# Used by the calendar-month rollup to lift highlighted rows into its own
# ``<details class="highlights">`` block at the top of the page. Only majors
# are highlighted now; legacy ``data-highlight="minor"`` rows in older weekly
# HTML files are intentionally NOT matched here.
_RELEASE_LI_HIGHLIGHT_RE = re.compile(
    r'<li class="release"[^>]*\sdata-highlight="(major)"',
    re.IGNORECASE,
)
# Anchor used by the calendar rollup to inject the project label into a lifted
# highlighted ``<li>``: the row starts ``<div class="release-meta">…``.
_RELEASE_META_OPEN_RE = re.compile(r'<div class="release-meta">', re.IGNORECASE)
# Legacy fallback: the date span just before the singleton ``link`` anchor in
# old on-disk weekly HTML that predates ``data-sort-date``.
_RELEASE_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})</span>\s*<span class=\"sep\">\|</span>\s*<a class=\"link\"",
    re.IGNORECASE,
)

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
.group-count { font-weight: 600; }
.group-artifacts {
  margin: 0.5rem 0 0;
  padding: 0.45rem 0.6rem 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  background: #f8fafc;
  border-left: 3px solid #cbd5e1;
  border-radius: 4px;
}
.group-artifact {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem 0.5rem;
  align-items: baseline;
  font-size: 0.88rem;
  color: var(--text);
}
.group-artifact .sep { color: var(--border); user-select: none; }
.group-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.group-more {
  font-size: 0.82rem;
  font-style: italic;
  color: var(--muted);
}
details.highlights {
  margin: 0 0 1.5rem;
  background: #fff7ed;
  border: 1px solid #fdba74;
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}
details.highlights > summary {
  cursor: pointer;
  list-style: none;
  padding: 0.85rem 1.1rem;
  font-weight: 650;
  font-size: 1rem;
  color: #9a3412;
  background: linear-gradient(to bottom, #ffedd5, #fed7aa);
  user-select: none;
  letter-spacing: -0.01em;
}
details.highlights > summary::-webkit-details-marker { display: none; }
details.highlights > summary::marker { content: ""; }
details.highlights[open] > summary {
  border-bottom: 1px solid #fdba74;
}
details.highlights > summary:hover {
  background: linear-gradient(to bottom, #ffe4b5, #fdba74);
}
details.highlights .release {
  border-bottom: 1px solid #fed7aa;
}
details.highlights .release:last-child { border-bottom: none; }
.release-project {
  color: #0f172a;
  font-weight: 600;
}
"""


def _highlight_attr(group: ReleaseGroup) -> str:
    """Optional ``data-highlight="major|minor"`` attribute fragment for a row."""
    kind = group.highlight_kind
    if kind is None:
        return ""
    return f' data-highlight="{html.escape(kind)}"'


def _project_label_span(project: str) -> str:
    """Leading ``<span class="release-project mono">…</span>|`` meta column."""
    return (
        f'<span class="release-project mono">{html.escape(project)}</span>'
        '<span class="sep">|</span>'
    )


def _singleton_li_html(group: ReleaseGroup, *, include_project: bool = False) -> str:
    rel = group.members[0]
    date_value = html.escape(rel.released_at.date().isoformat())
    gh = html.escape(rel.github_repo) if rel.github_repo else "—"
    artifact = html.escape(rel.artifact)
    version = html.escape(rel.version)
    source = html.escape(rel.source)
    url_esc = html.escape(rel.url, quote=True)
    pub_raw = rel.publisher if rel.publisher else "—"
    pub = html.escape(pub_raw)
    parts = [
        f'<span class="mono">{gh}</span>',
        '<span class="sep">|</span>',
        f'<span class="source-tag">{source}</span>',
        '<span class="sep">|</span>',
        f'<span class="mono">{artifact}</span>',
        '<span class="sep">|</span>',
        f'<span class="mono">{version}</span>',
        '<span class="sep">|</span>',
        f"<span>{pub}</span>",
        '<span class="sep">|</span>',
        f"<span>{date_value}</span>",
        '<span class="sep">|</span>',
        f'<a class="link" href="{url_esc}">link</a>',
    ]
    project_prefix = _project_label_span(group.project) if include_project else ""
    meta = f'<div class="release-meta">{project_prefix}{"".join(parts)}</div>'
    desc_block = ""
    if rel.description:
        body = html.escape(rel.description).replace("\n", "<br>\n")
        desc_block = f'<p class="description">{body}</p>'
    return (
        f'<li class="release" data-sort-date="{date_value}"'
        f"{_highlight_attr(group)}>"
        f"{meta}{desc_block}</li>"
    )


def _grouped_li_html(group: ReleaseGroup, *, include_project: bool = False) -> str:
    sort_date = html.escape(group.sort_date_iso)
    gh_repo = group.github_repo_or_none
    gh = html.escape(gh_repo) if gh_repo else "—"
    sources = html.escape(", ".join(group.sources))
    version = html.escape(group.version_label)
    date_label = html.escape(group.date_label)
    pub_raw = group.publishers_merged if group.publishers_merged else "—"
    pub = html.escape(pub_raw)
    if group.is_pass1:
        count_label = f"{len(group.members)} artifacts"
    else:
        count_label = f"{len(group.members)} releases"
    count_esc = html.escape(count_label)
    parts = [
        f'<span class="mono">{gh}</span>',
        '<span class="sep">|</span>',
        f'<span class="source-tag">{sources}</span>',
        '<span class="sep">|</span>',
        f'<span class="mono group-count">{count_esc}</span>',
        '<span class="sep">|</span>',
        f'<span class="mono">{version}</span>',
        '<span class="sep">|</span>',
        f"<span>{pub}</span>",
        '<span class="sep">|</span>',
        f"<span>{date_label}</span>",
        '<span class="sep">|</span>',
        "<span>multiple</span>",
    ]
    project_prefix = _project_label_span(group.project) if include_project else ""
    meta = f'<div class="release-meta">{project_prefix}{"".join(parts)}</div>'

    desc_block = ""
    desc = group.description_first_nonempty
    if desc:
        body = html.escape(desc).replace("\n", "<br>\n")
        desc_block = f'<p class="description">{body}</p>'

    visible_artifacts, hidden_count = displayed_artifacts(group)
    artifacts_csv = html.escape(", ".join(visible_artifacts))
    more_span = (
        f' <span class="group-more">(+{hidden_count} more)</span>'
        if hidden_count
        else ""
    )
    versions_csv = html.escape(", ".join(group.versions))
    last_url = html.escape(group.members_sorted[-1].url, quote=True)
    sub_block = (
        '<div class="group-artifacts">'
        '<div class="group-artifact">'
        '<span class="group-label">Artifacts:</span> '
        f'<span class="mono">{artifacts_csv}</span>'
        f"{more_span}"
        '<span class="sep">|</span>'
        '<span class="group-label">Versions:</span> '
        f'<span class="mono">{versions_csv}</span>'
        '<span class="sep">|</span>'
        '<span class="group-label">Link:</span> '
        f'<a class="link" href="{last_url}">link</a>'
        "</div>"
        "</div>"
    )

    return (
        f'<li class="release" data-sort-date="{sort_date}"'
        f"{_highlight_attr(group)}>"
        f"{meta}{desc_block}{sub_block}"
        "</li>"
    )


def _release_li_html(group: ReleaseGroup, *, include_project: bool = False) -> str:
    if group.is_singleton:
        return _singleton_li_html(group, include_project=include_project)
    return _grouped_li_html(group, include_project=include_project)


def _render_highlights_section_html(groups: list[ReleaseGroup]) -> str:
    """Top-of-page collapsible ``<details class="highlights">`` block.

    Returns an empty string when no group qualifies. The lifted ``<li>`` rows
    mirror the per-project rows for the same group with one addition: each
    row's meta starts with a ``<span class="release-project mono">`` column so
    the reader can tell which project the highlight belongs to without
    expanding any project section.
    """
    highlights = select_highlight_groups(groups)
    if not highlights:
        return ""
    n = len(highlights)
    lis = "\n".join(_release_li_html(g, include_project=True) for g in highlights)
    return (
        '<details class="highlights">\n'
        "<summary>Highlights"
        f'<span class="summary-count"> ({n})</span></summary>\n'
        f'<ul class="releases">\n{lis}\n</ul>\n'
        "</details>\n"
    )


def render_html(target_date: date, releases: list[Release]) -> str:
    iso = target_date.isocalendar()
    title = f"FINOS releases for {iso.year} week {iso.week:02d}"
    title_esc = html.escape(title)

    if not releases:
        body_inner = '<p class="empty">No releases found in this period.</p>'
    else:
        groups = cluster_releases(releases)
        blocks: list[str] = []
        # ``cluster_releases`` already returns groups sorted by
        # (project.casefold(), project, sort_datetime), so ``groupby`` produces
        # one section per project in the right order.
        for project, project_groups in groupby(groups, key=lambda g: g.project):
            group_list = list(project_groups)
            n = len(group_list)
            proj_esc = html.escape(project)
            lis = "\n".join(_release_li_html(g) for g in group_list)
            blocks.append(
                f'<details class="project">\n'
                f"<summary>{proj_esc}"
                f'<span class="summary-count"> ({n})</span></summary>\n'
                f'<ul class="releases">\n{lis}\n</ul>\n'
                f"</details>"
            )
        highlights_section = _render_highlights_section_html(groups)
        body_inner = (
            f"{highlights_section}" f'<div class="projects">\n{"".join(blocks)}\n</div>'
        )

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
<p>FINOS community releases (UTC), grouped by project. Release rows show
<strong>contributors</strong> (comma-separated when known) in the fifth column.</p>
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
        groups = cluster_releases(releases)
        highlights = select_highlight_groups(groups)
        if highlights:
            lines.append("")
            lines.append("<details>")
            lines.append("<summary>Highlights</summary>")
            lines.append("")
            for grp in highlights:
                lines.append(render_group_markdown(grp, include_project=True))
            lines.append("")
            lines.append("</details>")
        for project, project_groups in groupby(groups, key=lambda g: g.project):
            lines.append("")
            lines.append("<details>")
            lines.append(f"<summary>{html.escape(project)}</summary>")
            lines.append("")
            for grp in project_groups:
                lines.append(render_group_markdown(grp))
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
.week-links,
.month-links {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 0.65rem;
}
.week-links a,
.month-links a {
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
.week-links a:hover,
.month-links a:hover {
  border-color: var(--accent);
  background: #eff6ff;
}
.empty-year {
  margin: 0;
  color: var(--muted);
  font-size: 0.92rem;
}
.year-browse {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.25rem 1.5rem;
  align-items: start;
}
@media (max-width: 720px) {
  .year-browse { grid-template-columns: 1fr; }
}
.browse-heading {
  margin: 0 0 0.65rem;
  font-size: 0.78rem;
  font-weight: 650;
  text-transform: uppercase;
  letter-spacing: 0.045em;
  color: var(--muted);
}
.browse-column .week-links,
.browse-column .month-links { margin-top: 0; }
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


def _iso_week_calendar_month(iso_year: int, week: int) -> tuple[int, int]:
    """Gregorian (year, month) that contains the Thursday of the ISO week."""
    thursday = date.fromisocalendar(iso_year, week, 4)
    return thursday.year, thursday.month


def _group_weeks_by_calendar_month(
    iso_year: int, weeks: list[int]
) -> list[tuple[tuple[int, int], list[int]]]:
    buckets: dict[tuple[int, int], list[int]] = {}
    for w in weeks:
        key = _iso_week_calendar_month(iso_year, w)
        buckets.setdefault(key, []).append(w)
    for wlist in buckets.values():
        wlist.sort()
    return sorted(buckets.items(), key=lambda item: item[0])


def _release_li_sort_key(li_html: str) -> str:
    """Date used to order ``<li class="release">`` rows in calendar rollups.

    Prefers the explicit ``data-sort-date="YYYY-MM-DD"`` attribute (= earliest
    underlying release date for grouped rows). Falls back to the meta-row date
    span for backward compatibility with weekly HTML written before the
    attribute existed.
    """
    m = _RELEASE_LI_DATA_SORT_RE.search(li_html)
    if m:
        return m.group(1)
    m = _RELEASE_DATE_RE.search(li_html)
    return m.group(1) if m else ""


def parse_weekly_html_project_blocks(page_html: str) -> dict[str, list[str]]:
    """Parse a saved weekly ``render_html`` document into project label → ``<li>`` HTML."""
    out: dict[str, list[str]] = {}
    for m in _WEEKLY_PROJECT_BLOCK_RE.finditer(page_html):
        summary_inner = m.group("summary").strip()
        label_key = _SUMMARY_COUNT_SPAN_RE.sub("", summary_inner).strip()
        if not label_key:
            continue
        ulbody = m.group("ulbody")
        items = [mm.group(0) for mm in _RELEASE_LI_RE.finditer(ulbody)]
        if not items:
            continue
        out.setdefault(label_key, []).extend(items)
    return out


def merge_calendar_month_project_lists(
    per_week: list[dict[str, list[str]]],
) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for week_map in per_week:
        for proj, items in week_map.items():
            merged.setdefault(proj, []).extend(items)
    for _proj, items in merged.items():
        items.sort(key=_release_li_sort_key)
    return merged


def _inject_project_label_into_li(li_html: str, project_label_html: str) -> str:
    """Insert a leading ``<span class="release-project mono">…</span>|`` column.

    ``project_label_html`` is taken verbatim from the weekly ``<details
    class="project"><summary>…</summary>`` payload (which is already
    HTML-escaped by ``render_html``), so it is splice-safe.
    """
    label_span = (
        f'<span class="release-project mono">{project_label_html}</span>'
        '<span class="sep">|</span>'
    )
    return _RELEASE_META_OPEN_RE.sub(
        f'<div class="release-meta">{label_span}', li_html, count=1
    )


def collect_highlighted_lis(per_week: list[dict[str, list[str]]]) -> list[str]:
    """Flat list of major-highlighted ``<li class="release">`` rows across maps.

    Picks every row carrying ``data-highlight="major"`` from the parsed weekly
    project maps, **injects the project label** (taken from the enclosing
    ``<details class="project"><summary>`` so calendar Highlights rows look
    the same as weekly Highlights rows) and orders the result by
    ``data-sort-date`` ascending. Weekly files written before the
    ``data-highlight`` attribute existed contribute nothing; legacy
    ``data-highlight="minor"`` rows from older weekly HTML are intentionally
    **ignored** because minor releases are no longer highlighted.
    """
    flat: list[tuple[str, str]] = []
    for week_map in per_week:
        for project_label_html, items in week_map.items():
            for li in items:
                if _RELEASE_LI_HIGHLIGHT_RE.search(li) is None:
                    continue
                augmented = _inject_project_label_into_li(li, project_label_html)
                flat.append((_release_li_sort_key(li), augmented))
    flat.sort(key=lambda t: t[0])
    return [li for _, li in flat]


def render_calendar_month_html(
    calendar_year: int,
    calendar_month: int,
    projects: dict[str, list[str]],
    *,
    highlighted: list[str] | None = None,
) -> str:
    """Standalone HTML for one Gregorian month (same layout as ``render_html``)."""
    month_name = _MONTH_NAMES_EN[calendar_month - 1]
    title = f"FINOS releases for {month_name} {calendar_year}"
    title_esc = html.escape(title)
    if not projects:
        body_inner = '<p class="empty">No releases found in this period.</p>'
    else:
        blocks: list[str] = []
        for proj_label_html, group_items in sorted(
            projects.items(), key=lambda kv: (kv[0].lower(), kv[0])
        ):
            n = len(group_items)
            lis = "\n".join(group_items)
            blocks.append(
                f'<details class="project">\n'
                f"<summary>{proj_label_html}"
                f'<span class="summary-count"> ({n})</span></summary>\n'
                f'<ul class="releases">\n{lis}\n</ul>\n'
                f"</details>"
            )
        highlights_html = ""
        if highlighted:
            joined = "\n".join(highlighted)
            n = len(highlighted)
            highlights_html = (
                '<details class="highlights">\n'
                "<summary>Highlights"
                f'<span class="summary-count"> ({n})</span></summary>\n'
                f'<ul class="releases">\n{joined}\n</ul>\n'
                "</details>\n"
            )
        body_inner = (
            f"{highlights_html}" f'<div class="projects">\n{"".join(blocks)}\n</div>'
        )
    header_p = (
        "FINOS community releases (UTC) for this calendar month, grouped by project. "
        "Built from ISO week HTML files whose Thursday falls in this month. "
        "Release rows show <strong>contributors</strong> (comma-separated when known) "
        "in the fifth column."
    )
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
<p>{header_p}</p>
</header>
<main>
{body_inner}
</main>
</div>
</body>
</html>
"""


def _calendar_month_href(iso_year: int, cal_year: int, cal_month: int) -> str:
    return f"{iso_year}/calendar-{cal_year}-{cal_month:02d}.html"


def _render_index_month_page_link(iso_year: int, cal_year: int, cal_month: int) -> str:
    href = html.escape(_calendar_month_href(iso_year, cal_year, cal_month), quote=True)
    label = html.escape(f"{_MONTH_NAMES_EN[cal_month - 1]} {cal_year}")
    return f'<li><a href="{href}">{label}</a></li>'


def write_calendar_month_pages(base_dir: Path) -> None:
    """Write ``calendar-YYYY-MM.html`` under each ISO week-year folder from week reports."""
    raw_rows = collect_year_week_html_files(base_dir)
    for iso_year, weeks in raw_rows:
        if iso_year < _INDEX_EPOCH_ISO_YEAR or not weeks:
            continue
        for (gy, gm), wk_list in _group_weeks_by_calendar_month(iso_year, weeks):
            per_week: list[dict[str, list[str]]] = []
            for w in sorted(wk_list):
                path = base_dir / str(iso_year) / f"{w:02d}.html"
                if not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                per_week.append(parse_weekly_html_project_blocks(text))
            merged = merge_calendar_month_project_lists(per_week)
            highlighted = collect_highlighted_lis(per_week)
            out_path = base_dir / str(iso_year) / f"calendar-{gy}-{gm:02d}.html"
            out_path.write_text(
                render_calendar_month_html(gy, gm, merged, highlighted=highlighted),
                encoding="utf-8",
            )


def _render_index_week_links(year: int, week_nums: list[int]) -> str:
    lis: list[str] = []
    for w in week_nums:
        href = html.escape(f"{year}/{w:02d}.html", quote=True)
        label = html.escape(f"Week {w:02d}")
        lis.append(f'<li><a href="{href}">{label}</a></li>')
    return f'<ul class="week-links">\n{"".join(lis)}\n</ul>'


def render_releases_index_html(base_dir: Path) -> str:
    """Standalone HTML listing each year folder and links to ``WW.html`` week reports."""
    raw_rows = collect_year_week_html_files(base_dir)
    rows = [(y, w) for y, w in raw_rows if y >= _INDEX_EPOCH_ISO_YEAR]
    title = "FINOS Releases"
    title_esc = html.escape(title)
    if not raw_rows:
        main_inner = (
            '<p class="empty-year">No year folders or HTML week reports yet.</p>'
        )
    elif not rows:
        main_inner = (
            '<p class="empty-year">'
            f"No HTML week reports for {_INDEX_EPOCH_ISO_YEAR} or later yet.</p>"
        )
    else:
        sections: list[str] = []
        for year, weeks in rows:
            y_esc = html.escape(str(year))
            if weeks:
                month_items = [
                    _render_index_month_page_link(year, gy, gm)
                    for (gy, gm), _wks in _group_weeks_by_calendar_month(year, weeks)
                ]
                months_html = f'<ul class="month-links">\n{"".join(month_items)}\n</ul>'
                weeks_html = _render_index_week_links(year, weeks)
                inner = (
                    f'<div class="year-browse">\n'
                    f'<div class="browse-column">\n'
                    f'<h3 class="browse-heading">By month</h3>\n'
                    f"{months_html}\n"
                    f"</div>\n"
                    f'<div class="browse-column">\n'
                    f'<h3 class="browse-heading">By week</h3>\n'
                    f"{weeks_html}\n"
                    f"</div>\n"
                    f"</div>"
                )
            else:
                inner = '<p class="empty-year">No HTML week reports for this year.</p>'
            sections.append(
                f'<section class="year-block">\n<h2>{y_esc}</h2>\n{inner}\n</section>'
            )
        main_inner = "\n".join(sections)
    subtitle = (
        "Reports from 1&nbsp;January&nbsp;2026 (UTC). "
        "Week files use <code>YYYY/WW.html</code> (ISO week-year folder "
        "<code>YYYY/</code> and zero-padded week <code>WW</code>). "
        "Under <strong>By month</strong>, one page per Gregorian month "
        "(same Thursday rule as before) aggregates every week in that month, "
        "grouped by project. <strong>By week</strong> still links each "
        "<code>WW.html</code> file."
    )
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
<p>{subtitle}</p>
</header>
<main>
{main_inner}
</main>
</div>
</body>
</html>
"""


def write_releases_index(base_dir: Path) -> Path:
    """Write ``base_dir/index.html`` and ``calendar-YYYY-MM.html`` month rollups."""
    base_dir.mkdir(parents=True, exist_ok=True)
    write_calendar_month_pages(base_dir)
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
