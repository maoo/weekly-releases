from datetime import date, datetime, timezone
from pathlib import Path

from weekly_releases.models import Release
from weekly_releases.runner import fetch_all_finos_repo_names, run


class _Client:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _patch_common(monkeypatch):
    monkeypatch.setattr(
        "weekly_releases.runner.fetch_all_finos_repo_names", lambda _c: frozenset()
    )
    monkeypatch.setattr("weekly_releases.runner.load_landscape", lambda _=None: object())
    monkeypatch.setattr("weekly_releases.runner.httpx.Client", _Client)


def test_current_week_write_writes_single_week_file(monkeypatch, tmp_path: Path):
    _patch_common(monkeypatch)

    captured = {}

    def _crawl_github(ctx):
        captured["start"] = ctx.start.date().isoformat()
        captured["end"] = ctx.end.date().isoformat()
        return [
            Release(
                project="P",
                source="github",
                artifact="a",
                version="v2",
                url="https://e/2",
                released_at=datetime(2026, 1, 8, tzinfo=timezone.utc),
            ),
        ]

    monkeypatch.setattr("weekly_releases.runner.crawl_github", _crawl_github)
    monkeypatch.setattr("weekly_releases.runner.crawl_maven", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_npm", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_pypi", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_docker_hub", lambda ctx: [])

    messages: list[str] = []
    result = run(
        output_dir=tmp_path,
        today=date(2026, 1, 8),
        dry_run=False,
        current_week_only=True,
        progress=messages.append,
    )

    assert captured["start"] == "2026-01-05"
    assert captured["end"] == "2026-01-08"
    assert [p.name for p in result.output_files] == ["02.md"]
    assert result.output_files[0].exists()
    assert "v2" in result.output_files[0].read_text(encoding="utf-8")
    assert len(result.releases) == 1
    assert any("Current week only" in msg for msg in messages)


def test_current_week_write_does_not_touch_other_week_files(monkeypatch, tmp_path: Path):
    """Backfill path would write W01+W02 when missing; current-week only writes W02."""
    _patch_common(monkeypatch)

    monkeypatch.setattr("weekly_releases.runner.crawl_github", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_maven", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_npm", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_pypi", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_docker_hub", lambda ctx: [])

    result = run(
        output_dir=tmp_path,
        today=date(2026, 1, 8),
        dry_run=False,
        current_week_only=True,
    )

    assert [p.name for p in result.output_files] == ["02.md"]
    assert not (tmp_path / "2026" / "01.md").exists()


def test_dry_run_returns_only_current_week(monkeypatch, tmp_path: Path):
    _patch_common(monkeypatch)

    captured = {}

    def _crawl_github(ctx):
        captured["start"] = ctx.start.date().isoformat()
        captured["end"] = ctx.end.date().isoformat()
        return [
            Release(
                project="P",
                source="github",
                artifact="a",
                version="v",
                url="https://e",
                released_at=datetime(2026, 1, 7, 12, tzinfo=timezone.utc),
            )
        ]

    monkeypatch.setattr("weekly_releases.runner.crawl_github", _crawl_github)
    monkeypatch.setattr("weekly_releases.runner.crawl_maven", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_npm", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_pypi", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_docker_hub", lambda ctx: [])

    messages: list[str] = []
    result = run(
        output_dir=tmp_path,
        today=date(2026, 1, 8),
        dry_run=True,
        progress=messages.append,
    )

    # ISO week containing 2026-01-08 is W02 (Mon 2026-01-05 -> Sun 2026-01-11).
    assert captured["start"] == "2026-01-05"
    assert captured["end"] == "2026-01-08"
    assert result.output_files == []
    assert len(result.releases) == 1
    assert any("Crawling GitHub" in msg for msg in messages)
    assert any("Dry run" in msg for msg in messages)


def test_write_run_creates_one_file_per_missing_week(monkeypatch, tmp_path: Path):
    _patch_common(monkeypatch)

    captured = {}

    def _crawl_github(ctx):
        captured["start"] = ctx.start.date().isoformat()
        captured["end"] = ctx.end.date().isoformat()
        return [
            Release(
                project="P",
                source="github",
                artifact="a",
                version="v1",
                url="https://e/1",
                released_at=datetime(2026, 1, 2, tzinfo=timezone.utc),  # W01
            ),
            Release(
                project="P",
                source="github",
                artifact="a",
                version="v2",
                url="https://e/2",
                released_at=datetime(2026, 1, 8, tzinfo=timezone.utc),  # W02
            ),
        ]

    monkeypatch.setattr("weekly_releases.runner.crawl_github", _crawl_github)
    monkeypatch.setattr("weekly_releases.runner.crawl_maven", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_npm", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_pypi", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_docker_hub", lambda ctx: [])

    result = run(output_dir=tmp_path, today=date(2026, 1, 8), dry_run=False)

    # Today is W02; W01 and W02 are both missing -> two files written.
    assert [p.name for p in result.output_files] == ["01.md", "02.md"]
    assert all(p.exists() for p in result.output_files)
    assert (tmp_path / "2026" / "01.md").read_text(encoding="utf-8").count("v1") == 1
    assert (tmp_path / "2026" / "02.md").read_text(encoding="utf-8").count("v2") == 1
    # Crawl range spans from W01 start through end of today.
    assert captured["start"] == "2025-12-29"
    assert captured["end"] == "2026-01-08"


def test_write_run_skips_existing_weeks(monkeypatch, tmp_path: Path):
    _patch_common(monkeypatch)

    # W01 already exists; only W02 should be written.
    existing = tmp_path / "2026" / "01.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("preexisting", encoding="utf-8")

    captured = {}

    def _crawl(ctx):
        captured["start"] = ctx.start.date().isoformat()
        return []

    monkeypatch.setattr("weekly_releases.runner.crawl_github", _crawl)
    monkeypatch.setattr("weekly_releases.runner.crawl_maven", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_npm", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_pypi", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_docker_hub", lambda ctx: [])

    result = run(output_dir=tmp_path, today=date(2026, 1, 8), dry_run=False)

    assert [p.name for p in result.output_files] == ["02.md"]
    # Existing W01 was not overwritten.
    assert existing.read_text(encoding="utf-8") == "preexisting"
    # Crawl starts at the earliest missing week (W02 -> Mon 2026-01-05).
    assert captured["start"] == "2026-01-05"


def test_write_run_skips_when_all_weeks_present(monkeypatch, tmp_path: Path):
    _patch_common(monkeypatch)

    crawled = {"called": False}

    def _crawl(ctx):
        crawled["called"] = True
        return []

    monkeypatch.setattr("weekly_releases.runner.crawl_github", _crawl)
    monkeypatch.setattr("weekly_releases.runner.crawl_maven", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_npm", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_pypi", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_docker_hub", lambda ctx: [])

    # Pre-populate W01 and W02.
    for week in ("01", "02"):
        path = tmp_path / "2026" / f"{week}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("done", encoding="utf-8")

    messages: list[str] = []
    result = run(
        output_dir=tmp_path,
        today=date(2026, 1, 8),
        dry_run=False,
        progress=messages.append,
    )

    assert result.output_files == []
    assert result.releases == []
    assert crawled["called"] is False
    assert any("nothing to do" in msg for msg in messages)


def test_write_run_writes_empty_files_for_weeks_with_no_releases(
    monkeypatch, tmp_path: Path
):
    _patch_common(monkeypatch)
    monkeypatch.setattr("weekly_releases.runner.crawl_github", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_maven", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_npm", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_pypi", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_docker_hub", lambda ctx: [])

    result = run(output_dir=tmp_path, today=date(2026, 1, 8), dry_run=False)

    # W01 and W02 are missing; both should be written, both empty.
    assert [p.name for p in result.output_files] == ["01.md", "02.md"]
    for path in result.output_files:
        assert "No releases found" in path.read_text(encoding="utf-8")


def test_run_continues_after_source_failure(monkeypatch, tmp_path: Path):
    _patch_common(monkeypatch)

    def _boom(ctx):
        import httpx

        raise httpx.ProxyError("blocked")

    monkeypatch.setattr("weekly_releases.runner.crawl_github", _boom)
    monkeypatch.setattr("weekly_releases.runner.crawl_maven", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_npm", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_pypi", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_docker_hub", lambda ctx: [])

    messages: list[str] = []
    result = run(
        output_dir=tmp_path,
        today=date(2026, 1, 8),
        dry_run=True,
        progress=messages.append,
    )
    assert result.releases == []
    assert any("skipped due to HTTP error" in msg for msg in messages)


def test_run_continues_after_unexpected_error(monkeypatch, tmp_path: Path):
    _patch_common(monkeypatch)

    def _boom(ctx):
        raise RuntimeError("oops")

    monkeypatch.setattr("weekly_releases.runner.crawl_github", _boom)
    monkeypatch.setattr("weekly_releases.runner.crawl_maven", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_npm", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_pypi", lambda ctx: [])
    monkeypatch.setattr("weekly_releases.runner.crawl_docker_hub", lambda ctx: [])

    messages: list[str] = []
    result = run(
        output_dir=tmp_path,
        today=date(2026, 1, 8),
        dry_run=True,
        progress=messages.append,
    )
    assert result.releases == []
    assert any("skipped due to unexpected error" in msg for msg in messages)


def test_fetch_all_finos_repo_names_follows_next_link():
    calls = {"n": 0}

    class Resp:
        def __init__(self, names: list[str], link: str | None):
            self.names = names
            self.headers = {"Link": link} if link else {}

        def raise_for_status(self):
            return None

        def json(self):
            return [{"name": n} for n in self.names]

    class Client:
        def get(self, url, headers=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return Resp(
                    ["a"],
                    '<https://api.github.com/orgs/finos/repos?page=2>; rel="next"',
                )
            return Resp(["b"], None)

    names = fetch_all_finos_repo_names(Client())
    assert names == frozenset({"a", "b"})
