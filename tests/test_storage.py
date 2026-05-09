from datetime import UTC, date, datetime
from pathlib import Path

from weekly_releases.models import Release
from weekly_releases.storage import (
    collect_year_week_html_files,
    latest_weekly_file,
    render_html,
    render_markdown,
    render_releases_index_html,
    write_releases_index,
    write_weekly_file,
)


def test_render_markdown_escapes_summary_html():
    rel = Release(
        project="Fish & Chips <special>",
        source="github",
        artifact="r",
        version="1",
        url="https://example.test",
        released_at=datetime(2026, 1, 8, tzinfo=UTC),
    )
    md = render_markdown(date(2026, 1, 8), [rel])
    assert "<summary>Fish &amp; Chips &lt;special&gt;</summary>" in md


def test_render_markdown_with_and_without_releases():
    empty = render_markdown(date(2026, 1, 8), [])
    assert "No releases found" in empty

    release = Release(
        project="Proj",
        source="github",
        artifact="repo",
        version="v1",
        url="https://example.test",
        released_at=datetime(2026, 1, 8, tzinfo=UTC),
    )
    full = render_markdown(date(2026, 1, 8), [release])
    assert "<summary>Proj</summary>" in full
    assert "<details>" in full and "</details>" in full
    assert "`Proj` |" not in full  # project shown only in heading when grouped
    assert " — " in full
    assert "[link](https://example.test)" in full

    with_desc = Release(
        project="Proj",
        source="github",
        artifact="repo",
        version="v1",
        url="https://example.test",
        released_at=datetime(2026, 1, 8, tzinfo=UTC),
        description="Ships the initial API.",
    )
    md = render_markdown(date(2026, 1, 8), [with_desc])
    assert "<summary>Proj</summary>" in md
    assert "Description: Ships the initial API." in md


def test_render_markdown_groups_projects_sorted_and_omits_duplicate_label():
    early = Release(
        project="Zebra",
        source="github",
        artifact="z",
        version="1",
        url="https://z.test",
        released_at=datetime(2026, 1, 7, tzinfo=UTC),
    )
    late_same = Release(
        project="Zebra",
        source="docker",
        artifact="finos/z",
        version="2",
        url="https://hub.docker.com/r/finos/z/tags",
        released_at=datetime(2026, 1, 9, tzinfo=UTC),
    )
    apple = Release(
        project="Apple",
        source="github",
        artifact="a",
        version="1",
        url="https://a.test",
        released_at=datetime(2026, 1, 10, tzinfo=UTC),
    )
    md = render_markdown(date(2026, 1, 8), [early, apple, late_same])
    assert md.index("<summary>Apple</summary>") < md.index("<summary>Zebra</summary>")
    zebra_section = md.split("<summary>Zebra</summary>", 1)[1].split("</details>", 1)[0]
    assert zebra_section.index("docker") > zebra_section.index("github")
    assert "`Zebra` |" not in md


def test_latest_weekly_file_none_when_directory_does_not_exist(tmp_path: Path):
    assert latest_weekly_file(tmp_path / "absent") is None


def test_latest_weekly_file_none_when_no_release_files(tmp_path: Path):
    (tmp_path / "2026").mkdir()
    assert latest_weekly_file(tmp_path) is None


def test_latest_weekly_file_none_when_only_non_year_directories(tmp_path: Path):
    (tmp_path / "draft").mkdir()
    assert latest_weekly_file(tmp_path) is None


def test_write_and_find_latest(tmp_path: Path):
    rel = Release(
        project="Proj",
        source="npm",
        artifact="pkg",
        version="1.0.0",
        url="https://example.test/pkg",
        released_at=datetime(2026, 1, 8, tzinfo=UTC),
    )
    out = write_weekly_file(tmp_path, date(2026, 1, 8), [rel])
    assert out.suffix == ".html"
    assert out.exists()
    latest = latest_weekly_file(tmp_path)
    assert latest == out


def test_write_weekly_file_markdown(tmp_path: Path):
    rel = Release(
        project="Proj",
        source="npm",
        artifact="pkg",
        version="1.0.0",
        url="https://example.test/pkg",
        released_at=datetime(2026, 1, 8, tzinfo=UTC),
    )
    out = write_weekly_file(tmp_path, date(2026, 1, 8), [rel], output_format="md")
    assert out.suffix == ".md"
    assert "<summary>Proj</summary>" in out.read_text(encoding="utf-8")


def test_render_html_standalone_document_and_collapsed_details():
    rel = Release(
        project="A & B",
        source="github",
        artifact="x",
        version="1",
        url="https://example.test/u?v=1&x",
        released_at=datetime(2026, 1, 8, tzinfo=UTC),
        description="Line1\n<script>alert(1)</script>",
    )
    html_out = render_html(date(2026, 1, 8), [rel])
    assert "<!DOCTYPE html>" in html_out
    assert '<details class="project">' in html_out
    assert '<details class="project" open' not in html_out
    assert "A &amp; B" in html_out
    assert "<script>" not in html_out
    assert "example.test" in html_out


def test_render_html_empty_week():
    out = render_html(date(2026, 1, 8), [])
    assert "No releases found" in out
    assert "empty" in out


def test_latest_weekly_file_prefers_html_when_same_week(tmp_path: Path):
    y = tmp_path / "2026"
    y.mkdir(parents=True)
    md = y / "03.md"
    h = y / "03.html"
    md.write_text("x", encoding="utf-8")
    h.write_text("y", encoding="utf-8")
    assert latest_weekly_file(tmp_path) == h


def test_collect_year_week_html_files_requires_existing_base(tmp_path: Path):
    absent = tmp_path / "missing"
    assert collect_year_week_html_files(absent) == []


def test_collect_year_week_html_files_sorts_years_and_weeks_ignores_non_digit_dirs(
    tmp_path: Path,
):
    (tmp_path / "draft").mkdir()
    y2027 = tmp_path / "2027"
    y2027.mkdir()
    (y2027 / "03.html").write_text("a", encoding="utf-8")
    y2026 = tmp_path / "2026"
    y2026.mkdir()
    (y2026 / "02.html").write_text("b", encoding="utf-8")
    (y2026 / "10.html").write_text("c", encoding="utf-8")
    (y2026 / "readme.txt").write_text("x", encoding="utf-8")
    (y2026 / "bad.html").write_text("x", encoding="utf-8")
    (y2026 / "01.md").write_text("md only", encoding="utf-8")

    assert collect_year_week_html_files(tmp_path) == [
        (2026, [2, 10]),
        (2027, [3]),
    ]


def test_collect_year_week_html_files_includes_year_without_html_weeks(tmp_path: Path):
    (tmp_path / "2026").mkdir()
    assert collect_year_week_html_files(tmp_path) == [(2026, [])]


def test_render_releases_index_html_empty_base_has_notice(tmp_path: Path):
    html_out = render_releases_index_html(tmp_path)
    assert "<!DOCTYPE html>" in html_out
    assert "No year folders or HTML week reports yet." in html_out


def test_render_releases_index_html_links_week_pages_relative(tmp_path: Path):
    y = tmp_path / "2026"
    y.mkdir(parents=True)
    (y / "02.html").write_text("x", encoding="utf-8")
    (y / "01.html").write_text("y", encoding="utf-8")

    html_out = render_releases_index_html(tmp_path)
    assert 'href="2026/01.html"' in html_out
    assert 'href="2026/02.html"' in html_out
    assert html_out.index('href="2026/01.html"') < html_out.index('href="2026/02.html"')


def test_render_releases_index_html_shows_empty_notice_when_year_has_no_html(
    tmp_path: Path,
):
    (tmp_path / "2026").mkdir()
    html_out = render_releases_index_html(tmp_path)
    assert "<h2>2026</h2>" in html_out
    assert "No HTML week reports for this year." in html_out


def test_write_releases_index_creates_directory_and_index(tmp_path: Path):
    base = tmp_path / "out" / "releases"
    path = write_releases_index(base)
    assert path == base / "index.html"
    assert path.exists()
    assert "FINOS weekly releases" in path.read_text(encoding="utf-8")
