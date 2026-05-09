from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from weekly_releases.github_auth import (
    github_api_headers,
    github_auth_configured,
    github_token_from_env,
)
from weekly_releases.landscape import load_landscape
from weekly_releases.models import Release
from weekly_releases.sources import (
    SourceContext,
    crawl_docker_hub,
    crawl_github,
    crawl_maven,
    crawl_npm,
    crawl_pypi,
)
from weekly_releases.storage import write_releases_index, write_weekly_file
from weekly_releases.timebox import (
    OutputFormat,
    current_week_bounds,
    iso_week_bounds,
    iso_week_file,
    iso_weeks_between,
    release_iso_week,
)

# Backfill anchor: the project tracks weeks starting from this date onward.
EPOCH_DATE = date(2026, 1, 1)


@contextmanager
def _scan_http_client(report: Callable[[str], None]) -> Iterator[httpx.Client]:
    if github_auth_configured():
        report("GitHub API authenticated (GITHUB_TOKEN or GH_TOKEN)")
    else:
        report(
            "GitHub API unauthenticated — set GITHUB_TOKEN or GH_TOKEN to raise rate limits"
        )
    with httpx.Client(timeout=30.0) as client:
        yield client


def _github_next_page(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for segment in link_header.split(","):
        if 'rel="next"' not in segment:
            continue
        part = segment.split(";")[0].strip()
        if part.startswith("<") and part.endswith(">"):
            return part[1:-1]
    return None


def fetch_all_finos_repo_names(client: httpx.Client) -> frozenset[str]:
    """All public repository names under github.com/finos (paginated)."""
    names: set[str] = set()
    url: str | None = "https://api.github.com/orgs/finos/repos?per_page=100"
    while url:
        resp = client.get(url, headers=github_api_headers())
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403 and github_token_from_env() is None:
                msg = (
                    "GitHub API returned 403 (often rate limit). "
                    "Set GITHUB_TOKEN or GH_TOKEN to authenticate."
                )
                raise RuntimeError(msg) from exc
            raise
        data = resp.json()
        if not isinstance(data, list):
            break
        for repo in data:
            if isinstance(repo, dict) and isinstance(repo.get("name"), str):
                names.add(repo["name"])
        url = _github_next_page(resp.headers.get("Link"))
    return frozenset(names)


@dataclass(slots=True)
class RunResult:
    output_files: list[Path]
    releases: list[Release]


def _crawl_with_guard(
    context: SourceContext,
    label: str,
    crawler: Callable[[SourceContext], list[Release]],
    report: Callable[[str], None],
) -> list[Release]:
    try:
        report(f"Crawling {label}")
        result = crawler(context)
        report(f"{label}: {len(result)} releases")
        return result
    except httpx.HTTPError as exc:
        report(f"{label}: skipped due to HTTP error ({exc})")
        return []
    except Exception as exc:
        report(f"{label}: skipped due to unexpected error ({exc})")
        return []


def _crawl_all_sources(
    context: SourceContext, report: Callable[[str], None]
) -> list[Release]:
    releases: list[Release] = []
    releases.extend(_crawl_with_guard(context, "GitHub", crawl_github, report))
    releases.extend(_crawl_with_guard(context, "Maven", crawl_maven, report))
    releases.extend(_crawl_with_guard(context, "npm", crawl_npm, report))
    releases.extend(_crawl_with_guard(context, "PyPI", crawl_pypi, report))
    releases.extend(_crawl_with_guard(context, "Docker", crawl_docker_hub, report))
    return releases


def _build_context(
    start: datetime,
    end: datetime,
    landscape_source: str | None,
    report: Callable[[str], None],
    client: httpx.Client,
) -> SourceContext:
    report("Loading FINOS landscape mapping")
    landscape = load_landscape(landscape_source)
    report("Loading FINOS GitHub repository list")
    finos_repos = fetch_all_finos_repo_names(client)
    report(f"Indexed {len(finos_repos)} finos GitHub repos")
    return SourceContext(
        start=start,
        end=end,
        landscape=landscape,
        client=client,
        finos_repo_names=finos_repos,
        progress=report,
    )


def _missing_weeks(
    output_dir: Path, today: date, output_format: OutputFormat
) -> list[tuple[int, int]]:
    """ISO weeks from EPOCH_DATE through ``today`` that lack an output file for ``output_format``."""
    missing: list[tuple[int, int]] = []
    for year, week in iso_weeks_between(EPOCH_DATE, today):
        target = date.fromisocalendar(year, week, 1)
        if not iso_week_file(output_dir, target, output_format=output_format).exists():
            missing.append((year, week))
    return missing


def _bucket_by_iso_week(
    releases: list[Release],
) -> dict[tuple[int, int], list[Release]]:
    buckets: dict[tuple[int, int], list[Release]] = defaultdict(list)
    for rel in releases:
        buckets[release_iso_week(rel.released_at)].append(rel)
    return buckets


def _releases_in_iso_week(
    releases: list[Release], year: int, week: int
) -> list[Release]:
    key = (year, week)
    return [rel for rel in releases if release_iso_week(rel.released_at) == key]


def run(
    output_dir: Path,
    today: date,
    dry_run: bool,
    landscape_source: str | None = None,
    progress: Callable[[str], None] | None = None,
    current_week_only: bool = False,
    *,
    output_format: OutputFormat = "html",
) -> RunResult:
    report = progress or (lambda _msg: None)

    if dry_run:
        return _run_dry(output_dir, today, landscape_source, report)
    if current_week_only:
        result = _run_current_week_write(
            output_dir, today, landscape_source, report, output_format=output_format
        )
        idx = write_releases_index(output_dir)
        report(f"Updated {idx}")
        return result
    result = _run_write(
        output_dir, today, landscape_source, report, output_format=output_format
    )
    idx = write_releases_index(output_dir)
    report(f"Updated {idx}")
    return result


def _run_dry(
    output_dir: Path,
    today: date,
    landscape_source: str | None,
    report: Callable[[str], None],
) -> RunResult:
    start, end = current_week_bounds(today)
    report(
        "Dry run: scanning current ISO week "
        f"{start.date().isoformat()} \u2192 {end.date().isoformat()}"
    )
    with _scan_http_client(report) as client:
        context = _build_context(start, end, landscape_source, report, client)
        releases = _crawl_all_sources(context, report)
    report(f"Dry run complete: {len(releases)} total releases")
    return RunResult(output_files=[], releases=releases)


def _run_current_week_write(
    output_dir: Path,
    today: date,
    landscape_source: str | None,
    report: Callable[[str], None],
    *,
    output_format: OutputFormat,
) -> RunResult:
    start, end = current_week_bounds(today)
    iso = today.isocalendar()
    report(
        "Current week only: scanning ISO week "
        f"{iso.year}-W{iso.week:02d} "
        f"({start.date().isoformat()} → {end.date().isoformat()})"
    )
    with _scan_http_client(report) as client:
        context = _build_context(start, end, landscape_source, report, client)
        all_releases = _crawl_all_sources(context, report)

    weekly = _releases_in_iso_week(all_releases, iso.year, iso.week)
    target_monday = date.fromisocalendar(iso.year, iso.week, 1)
    output_file = write_weekly_file(
        output_dir, target_monday, weekly, output_format=output_format
    )
    report(f"Wrote {len(weekly)} releases to {output_file}")
    return RunResult(output_files=[output_file], releases=weekly)


def _run_write(
    output_dir: Path,
    today: date,
    landscape_source: str | None,
    report: Callable[[str], None],
    *,
    output_format: OutputFormat,
) -> RunResult:
    missing = _missing_weeks(output_dir, today, output_format)
    if not missing:
        report(
            f"All weeks from {EPOCH_DATE.isoformat()} through "
            f"{today.isoformat()} are already present; nothing to do"
        )
        return RunResult(output_files=[], releases=[])

    report(
        f"Backfilling {len(missing)} missing week(s) since {EPOCH_DATE.isoformat()}: "
        + ", ".join(f"{y}-W{w:02d}" for y, w in missing)
    )

    earliest_year, earliest_week = missing[0]
    latest_year, latest_week = missing[-1]
    global_start, _ = iso_week_bounds(earliest_year, earliest_week)
    _, latest_week_end = iso_week_bounds(latest_year, latest_week)
    today_end = datetime.combine(today, datetime.max.time(), tzinfo=UTC)
    global_end = min(latest_week_end, today_end)

    report(
        "Scanning releases from "
        f"{global_start.date().isoformat()} to {global_end.date().isoformat()}"
    )
    with _scan_http_client(report) as client:
        context = _build_context(
            global_start, global_end, landscape_source, report, client
        )
        all_releases = _crawl_all_sources(context, report)

    buckets = _bucket_by_iso_week(all_releases)
    output_files: list[Path] = []
    for year, week in missing:
        weekly = buckets.get((year, week), [])
        target = date.fromisocalendar(year, week, 1)
        output_file = write_weekly_file(
            output_dir, target, weekly, output_format=output_format
        )
        output_files.append(output_file)
        report(f"Wrote {len(weekly)} releases to {output_file}")

    return RunResult(output_files=output_files, releases=all_releases)
