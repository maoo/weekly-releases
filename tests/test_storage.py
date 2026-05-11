from datetime import UTC, date, datetime
from pathlib import Path

from weekly_releases.models import Release
from weekly_releases.storage import (
    collect_year_week_html_files,
    latest_weekly_file,
    merge_calendar_month_project_lists,
    parse_weekly_html_project_blocks,
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
    assert "| — | 2026-01-08 |" in full  # publisher placeholder before date
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
        publisher="Ada <test> (alovelace)",
    )
    html_out = render_html(date(2026, 1, 8), [rel])
    assert "<!DOCTYPE html>" in html_out
    assert '<details class="project">' in html_out
    assert '<details class="project" open' not in html_out
    assert "A &amp; B" in html_out
    assert "<script>" not in html_out
    assert "example.test" in html_out
    assert "Ada &lt;test&gt; (alovelace)" in html_out


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


def _minimal_week_html_body(*, release_date: str = "2026-01-05") -> str:
    return f"""<!DOCTYPE html><html><body><div class="wrap"><main>
<div class="projects">
<details class="project">
<summary>DemoProj<span class="summary-count"> (1)</span></summary>
<ul class="releases">
<li class="release"><div class="release-meta"><span class="mono">finos/x</span><span class="sep">|</span><span class="source-tag">github</span><span class="sep">|</span><span class="mono">x</span><span class="sep">|</span><span class="mono">1</span><span class="sep">|</span><span>—</span><span class="sep">|</span><span>{release_date}</span><span class="sep">|</span><a class="link" href="https://example/">link</a></div></li>
</ul>
</details>
</div></main></body></html>"""


def test_render_releases_index_html_links_week_pages_relative(tmp_path: Path):
    y = tmp_path / "2026"
    y.mkdir(parents=True)
    (y / "02.html").write_text(
        _minimal_week_html_body(release_date="2026-01-08"), encoding="utf-8"
    )
    (y / "01.html").write_text(
        _minimal_week_html_body(release_date="2026-01-02"), encoding="utf-8"
    )

    write_releases_index(tmp_path)
    html_out = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'href="2026/01.html"' in html_out
    assert 'href="2026/02.html"' in html_out
    assert html_out.index('href="2026/01.html"') < html_out.index('href="2026/02.html"')
    assert "FINOS Releases" in html_out
    assert "By month" in html_out
    assert "By week" in html_out
    assert "January 2026" in html_out
    assert "calendar-2026-01.html" in html_out
    cal = tmp_path / "2026" / "calendar-2026-01.html"
    assert cal.exists()
    cal_html = cal.read_text(encoding="utf-8")
    assert "DemoProj" in cal_html
    assert cal_html.index("2026-01-02") < cal_html.index("2026-01-08")


def test_render_releases_index_html_month_groups_follow_calendar_order(tmp_path: Path):
    y = tmp_path / "2026"
    y.mkdir(parents=True)
    # ISO 2026 W05 Thursday is still in January; W06 Thursday is 2026-02-05.
    for w in (1, 2, 6):
        (y / f"{w:02d}.html").write_text(_minimal_week_html_body(), encoding="utf-8")

    write_releases_index(tmp_path)
    html_out = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert html_out.index("January 2026") < html_out.index("February 2026")
    assert "calendar-2026-01.html" in html_out
    assert "calendar-2026-02.html" in html_out


def test_render_releases_index_html_excludes_years_before_epoch(tmp_path: Path):
    y = tmp_path / "2025"
    y.mkdir(parents=True)
    (y / "50.html").write_text("x", encoding="utf-8")

    html_out = render_releases_index_html(tmp_path)
    assert "2026 or later yet" in html_out
    assert "<h2>2025</h2>" not in html_out


def test_render_releases_index_html_epoch_year_only_when_mixed_folders(tmp_path: Path):
    (tmp_path / "2025").mkdir()
    (tmp_path / "2025" / "01.html").write_text("a", encoding="utf-8")
    y = tmp_path / "2026"
    y.mkdir(parents=True)
    (y / "01.html").write_text("b", encoding="utf-8")

    html_out = render_releases_index_html(tmp_path)
    assert "<h2>2026</h2>" in html_out
    assert "<h2>2025</h2>" not in html_out


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
    assert "FINOS Releases" in path.read_text(encoding="utf-8")


def test_merge_calendar_month_combines_same_project_across_weeks():
    w1 = _minimal_week_html_body(release_date="2026-01-15")
    w2 = _minimal_week_html_body(release_date="2026-01-03")
    merged = merge_calendar_month_project_lists(
        [parse_weekly_html_project_blocks(w1), parse_weekly_html_project_blocks(w2)]
    )
    assert len(merged) == 1
    items = next(iter(merged.values()))
    assert len(items) == 2
    joined = "\n".join(items)
    assert joined.index("2026-01-03") < joined.index("2026-01-15")


# -- Release-grouping aware rendering --------------------------------------


def _grouped_releases_pass1() -> list[Release]:
    when = datetime(2026, 5, 5, tzinfo=UTC)
    return [
        Release(
            project="Foo",
            source="maven",
            artifact="org.finos.foo:bar",
            version="1.2.0",
            url="https://example.test/bar",
            released_at=when,
            github_repo="finos/foo",
        ),
        Release(
            project="Foo",
            source="maven",
            artifact="org.finos.foo:baz",
            version="1.2.0",
            url="https://example.test/baz",
            released_at=when,
            github_repo="finos/foo",
        ),
        Release(
            project="Foo",
            source="docker",
            artifact="finos/foo",
            version="1.2.0",
            url="https://hub.docker.com/r/finos/foo/tags",
            released_at=when,
            github_repo="finos/foo",
        ),
    ]


def test_render_html_pass1_group_collapses_to_single_li_with_artifact_count():
    rels = _grouped_releases_pass1()
    out = render_html(date(2026, 5, 4), rels)
    # Only one <li class="release"> in the entire document: the version 1.2.0
    # is "minor" via release_kind, but only majors are highlighted now, so the
    # row is NOT duplicated into the top-of-page Highlights block.
    assert out.count('<li class="release"') == 1
    projects_html = out.split('<div class="projects">', 1)[1]
    assert projects_html.count('<li class="release"') == 1
    # Project summary count reflects rendered rows (1), not raw releases (3).
    assert "<summary>Foo<span" in out
    assert "(1)</span>" in out
    # Group meta carries the count phrase and shared version/date.
    assert "3 artifacts" in out
    assert "1.2.0" in out
    assert "2026-05-05" in out
    # Nested <div class="group-artifacts"> wraps a SINGLE compact summary line
    # (Artifacts/Versions/Link), not one row per member. A <div> wrapper (not
    # <ul><li>) keeps the existing `<li class="release">.*?</li>` calendar
    # parser regex correct.
    assert '<div class="group-artifacts">' in out
    assert projects_html.count('<div class="group-artifact">') == 1
    assert '<span class="group-label">Artifacts:</span>' in out
    assert '<span class="group-label">Versions:</span>' in out
    assert '<span class="group-label">Link:</span>' in out
    # Distinct artifacts list lives on the summary line.
    assert "org.finos.foo:bar, org.finos.foo:baz, finos/foo" in out
    # Sources are joined comma-separated in the meta row.
    assert "maven, docker" in out or "docker, maven" in out
    # Only the LATEST member's URL surfaces in the summary line; here all three
    # share the same date so members_sorted breaks the tie by artifact name —
    # last entry is "org.finos.foo:baz".
    assert '<a class="link" href="https://example.test/baz">link</a>' in out


def test_render_html_singleton_carries_data_sort_date():
    rel = Release(
        project="Solo",
        source="github",
        artifact="r",
        version="v1",
        url="https://example.test",
        released_at=datetime(2026, 5, 7, tzinfo=UTC),
    )
    out = render_html(date(2026, 5, 4), [rel])
    assert 'data-sort-date="2026-05-07"' in out
    # Singleton path keeps the historical link anchor (one <a class="link">).
    assert '<a class="link"' in out


def test_render_html_grouped_row_emits_data_sort_date_earliest_member():
    rels = [
        Release(
            project="Foo",
            source="maven",
            artifact="x",
            version="1.0.0-dev.2",
            url="https://example.test/x",
            released_at=datetime(2026, 5, 7, tzinfo=UTC),
        ),
        Release(
            project="Foo",
            source="maven",
            artifact="y",
            version="1.0.0-dev.1",
            url="https://example.test/y",
            released_at=datetime(2026, 5, 5, tzinfo=UTC),
        ),
    ]
    out = render_html(date(2026, 5, 4), rels)
    assert 'data-sort-date="2026-05-05"' in out


def test_render_html_pass2_shows_version_and_date_range():
    rels = [
        Release(
            project="Foo",
            source="npm",
            artifact="@scope/pkg",
            version="7.0.0-dev.84",
            url="https://example.test/pkg/84",
            released_at=datetime(2026, 5, 4, tzinfo=UTC),
        ),
        Release(
            project="Foo",
            source="npm",
            artifact="@scope/pkg",
            version="7.0.0-dev.85",
            url="https://example.test/pkg/85",
            released_at=datetime(2026, 5, 6, tzinfo=UTC),
        ),
        Release(
            project="Foo",
            source="npm",
            artifact="@scope/pkg",
            version="7.0.0-dev.86",
            url="https://example.test/pkg/86",
            released_at=datetime(2026, 5, 8, tzinfo=UTC),
        ),
    ]
    out = render_html(date(2026, 5, 4), rels)
    assert out.count('<li class="release"') == 1
    assert "3 releases" in out
    assert "7.0.0-dev.84" in out
    assert "7.0.0-dev.86" in out
    assert "→" in out
    assert "2026-05-04" in out
    assert "2026-05-08" in out
    # The compact summary line lists every distinct version (not one row per
    # underlying release) and links only to the latest member.
    assert out.count('<div class="group-artifact">') == 1
    assert "7.0.0-dev.84, 7.0.0-dev.85, 7.0.0-dev.86" in out
    assert '<a class="link" href="https://example.test/pkg/86">link</a>' in out
    # Earlier-member URLs are intentionally not surfaced anymore.
    assert "/pkg/84" not in out
    assert "/pkg/85" not in out


def test_render_html_project_count_reflects_groups_not_raw_count():
    rels = _grouped_releases_pass1()
    out = render_html(date(2026, 5, 4), rels)
    # Three raw Releases collapse into one ReleaseGroup => count is (1).
    assert "(1)</span>" in out
    assert "(3)</span>" not in out


def test_render_html_grouped_row_truncates_artifact_list_at_twenty_shortest():
    when = datetime(2026, 5, 5, tzinfo=UTC)
    short_names = [f"s{i:02d}" for i in range(19)]
    long_names = ["really-long-artifact-name-" + str(i) for i in range(5)]
    rels = [
        Release(
            project="Foo",
            source="maven",
            artifact=name,
            version="1.0.0",
            url=f"https://example.test/{name}",
            released_at=when,
            github_repo="finos/foo",
        )
        for name in short_names + long_names
    ]
    out = render_html(date(2026, 5, 4), rels)
    # All 19 short names (3 chars each) made the cut.
    for name in short_names:
        assert name in out
    # All long names that exceed the cap (every long name except the
    # lexicographically first of the length-tied 5) are absent.
    cut_long = sorted(long_names)[1:]
    for name in cut_long:
        assert name not in out
    # Truncation indicator: explicit "(+M more)" suffix span.
    assert '<span class="group-more">(+4 more)</span>' in out
    # The meta-row count phrase still reports the TRUE artifact count.
    assert "24 artifacts" in out


def test_render_markdown_grouped_row_uses_compact_summary_line():
    rels = _grouped_releases_pass1()
    md = render_markdown(date(2026, 5, 4), rels)
    assert "<summary>Foo</summary>" in md
    # Only one top-level dash bullet for the group.
    foo_section = md.split("<summary>Foo</summary>", 1)[1].split("</details>", 1)[0]
    top_bullets = [line for line in foo_section.splitlines() if line.startswith("- ")]
    assert len(top_bullets) == 1
    assert "**3 artifacts**" in top_bullets[0]
    # Exactly one indented summary line, not one bullet per member.
    sub_bullets = [line for line in foo_section.splitlines() if line.startswith("  - ")]
    assert len(sub_bullets) == 1
    summary = sub_bullets[0]
    assert summary.startswith(
        "  - Artifacts: `org.finos.foo:bar`, `org.finos.foo:baz`, `finos/foo`"
    )
    assert "Versions: `1.2.0`" in summary
    # Per-member dates are omitted from the summary (already in meta date col).
    assert "2026-05-05" not in summary
    # Link points to the latest member.
    assert summary.endswith("| Link: [link](https://example.test/baz)")


def test_render_html_singleton_count_unchanged():
    rel = Release(
        project="Solo",
        source="github",
        artifact="r",
        version="v1",
        url="https://example.test",
        released_at=datetime(2026, 5, 7, tzinfo=UTC),
    )
    out = render_html(date(2026, 5, 4), [rel])
    assert "(1)</span>" in out


# -- Calendar rollup uses data-sort-date when present ----------------------


def _minimal_week_html_body_with_attr(
    *, sort_date: str, label: str = "DemoProj"
) -> str:
    return f"""<!DOCTYPE html><html><body><div class="wrap"><main>
<div class="projects">
<details class="project">
<summary>{label}<span class="summary-count"> (1)</span></summary>
<ul class="releases">
<li class="release" data-sort-date="{sort_date}"><div class="release-meta"><span class="mono">finos/x</span><span class="sep">|</span><span class="source-tag">github</span><span class="sep">|</span><span class="mono">x</span><span class="sep">|</span><span class="mono">1</span><span class="sep">|</span><span>—</span><span class="sep">|</span><span>{sort_date}</span><span class="sep">|</span><a class="link" href="https://example/">link</a></div></li>
</ul>
</details>
</div></main></body></html>"""


def test_calendar_rollup_sorts_grouped_rows_by_data_sort_date_attribute(
    tmp_path: Path,
):
    y = tmp_path / "2026"
    y.mkdir(parents=True)
    (y / "01.html").write_text(
        _minimal_week_html_body_with_attr(sort_date="2026-01-15"), encoding="utf-8"
    )
    (y / "02.html").write_text(
        _minimal_week_html_body_with_attr(sort_date="2026-01-03"), encoding="utf-8"
    )

    write_releases_index(tmp_path)
    cal = (tmp_path / "2026" / "calendar-2026-01.html").read_text(encoding="utf-8")
    assert "DemoProj" in cal
    assert cal.index("2026-01-03") < cal.index("2026-01-15")


def test_calendar_rollup_falls_back_to_meta_date_when_attribute_absent(
    tmp_path: Path,
):
    # Old-on-disk weekly HTML (no data-sort-date) still sorts correctly.
    y = tmp_path / "2026"
    y.mkdir(parents=True)
    (y / "01.html").write_text(
        _minimal_week_html_body(release_date="2026-01-15"), encoding="utf-8"
    )
    (y / "02.html").write_text(
        _minimal_week_html_body(release_date="2026-01-03"), encoding="utf-8"
    )

    write_releases_index(tmp_path)
    cal = (tmp_path / "2026" / "calendar-2026-01.html").read_text(encoding="utf-8")
    assert cal.index("2026-01-03") < cal.index("2026-01-15")


# -- Highlights section ----------------------------------------------------


def test_render_html_highlights_section_present_for_majors_only():
    rels = [
        Release(
            project="Alpha",
            source="github",
            artifact="alpha",
            version="2.0.0",
            url="https://example.test/alpha/2.0.0",
            released_at=datetime(2026, 5, 7, tzinfo=UTC),
            github_repo="finos/alpha",
        ),
        Release(
            project="Charlie",
            source="github",
            artifact="charlie",
            version="3.0.0",
            url="https://example.test/charlie/3.0.0",
            released_at=datetime(2026, 5, 5, tzinfo=UTC),
            github_repo="finos/charlie",
        ),
        Release(
            project="Beta",
            source="github",
            artifact="beta",
            version="3.4.0",
            url="https://example.test/beta/3.4.0",
            released_at=datetime(2026, 5, 5, tzinfo=UTC),
            github_repo="finos/beta",
        ),
        Release(
            project="Gamma",
            source="github",
            artifact="gamma",
            version="3.4.1",
            url="https://example.test/gamma/3.4.1",
            released_at=datetime(2026, 5, 6, tzinfo=UTC),
            github_repo="finos/gamma",
        ),
    ]
    out = render_html(date(2026, 5, 4), rels)
    # Highlights is a collapsible <details> block (no `open` => collapsed).
    assert '<details class="highlights">' in out
    assert '<details class="highlights" open' not in out
    assert "<summary>Highlights" in out
    # Highlights appear *before* the per-project content.
    assert out.index('<details class="highlights">') < out.index(
        '<div class="projects">'
    )
    highlights_html = out.split('<details class="highlights">', 1)[1].split(
        "</details>", 1
    )[0]
    # Both majors carry the project label as a leading meta column.
    assert '<span class="release-project mono">Alpha</span>' in highlights_html
    assert '<span class="release-project mono">Charlie</span>' in highlights_html
    # Charlie (2026-05-05, earlier) precedes Alpha (2026-05-07).
    assert highlights_html.index("Charlie") < highlights_html.index("Alpha")
    # Minor (Beta) and patch (Gamma) are NOT highlighted.
    assert "Beta" not in highlights_html
    assert "Gamma" not in highlights_html
    # Only major rows ever carry data-highlight; no minor marker exists.
    assert 'data-highlight="major"' in out
    assert 'data-highlight="minor"' not in out
    # All four projects still appear in their per-project sections below.
    projects_html = out.split('<div class="projects">', 1)[1]
    for proj in ("Alpha", "Beta", "Charlie", "Gamma"):
        assert proj in projects_html
    # Per-project rows do NOT carry the project-label span (project shown in summary).
    assert "release-project" not in projects_html


def test_render_html_omits_highlights_block_when_no_major():
    rels = [
        Release(
            project="Patchy",
            source="github",
            artifact="patchy",
            version="1.2.3",
            url="https://example.test",
            released_at=datetime(2026, 5, 7, tzinfo=UTC),
        ),
        Release(
            project="Pre",
            source="npm",
            artifact="pre",
            version="2.0.0-rc.1",
            url="https://example.test/pre",
            released_at=datetime(2026, 5, 7, tzinfo=UTC),
        ),
        Release(
            project="MinorOnly",
            source="github",
            artifact="m",
            version="2.3.0",
            url="https://example.test/m",
            released_at=datetime(2026, 5, 7, tzinfo=UTC),
        ),
    ]
    out = render_html(date(2026, 5, 4), rels)
    assert '<details class="highlights">' not in out
    assert "<summary>Highlights" not in out
    # Minor rows no longer carry data-highlight either.
    assert "data-highlight" not in out


def test_render_html_grouped_pass2_highlight_when_any_member_is_major():
    rels = [
        Release(
            project="Foo",
            source="npm",
            artifact="@scope/pkg",
            version="2.0.0-dev.5",
            url="https://example.test/pkg/dev5",
            released_at=datetime(2026, 5, 4, tzinfo=UTC),
        ),
        Release(
            project="Foo",
            source="npm",
            artifact="@scope/pkg",
            version="2.0.0",
            url="https://example.test/pkg/final",
            released_at=datetime(2026, 5, 7, tzinfo=UTC),
        ),
    ]
    out = render_html(date(2026, 5, 4), rels)
    assert '<details class="highlights">' in out
    assert 'data-highlight="major"' in out
    # The grouped <li> is duplicated into the highlights block.
    assert out.count('data-highlight="major"') == 2
    # Highlight row carries the project label; per-project row does not.
    highlights_html = out.split('<details class="highlights">', 1)[1].split(
        "</details>", 1
    )[0]
    assert '<span class="release-project mono">Foo</span>' in highlights_html


def test_render_markdown_highlights_block_lists_majors_only_by_date():
    rels = [
        Release(
            project="Alpha",
            source="github",
            artifact="alpha",
            version="2.0.0",
            url="https://example.test/alpha",
            released_at=datetime(2026, 5, 7, tzinfo=UTC),
        ),
        Release(
            project="Beta",
            source="github",
            artifact="beta",
            version="3.4.0",
            url="https://example.test/beta",
            released_at=datetime(2026, 5, 5, tzinfo=UTC),
        ),
        Release(
            project="Charlie",
            source="github",
            artifact="charlie",
            version="3.0.0",
            url="https://example.test/charlie",
            released_at=datetime(2026, 5, 5, tzinfo=UTC),
        ),
    ]
    md = render_markdown(date(2026, 5, 4), rels)
    # Highlights renders as a collapsible <details><summary>Highlights</summary>
    # block at the top.
    assert "<summary>Highlights</summary>" in md
    # Highlights summary appears before the first per-project <summary>.
    assert md.index("<summary>Highlights</summary>") < md.index("<summary>Alpha")
    highlights_chunk = md.split("<summary>Highlights</summary>", 1)[1].split(
        "</details>", 1
    )[0]
    # Only majors are listed; Beta (minor) is excluded.
    assert "`Alpha`" in highlights_chunk
    assert "`Charlie`" in highlights_chunk
    assert "`Beta`" not in highlights_chunk
    # Charlie (2026-05-05) precedes Alpha (2026-05-07) by date.
    assert highlights_chunk.index("`Charlie`") < highlights_chunk.index("`Alpha`")


def test_render_markdown_omits_highlights_when_no_major():
    rels = [
        Release(
            project="Patchy",
            source="github",
            artifact="patchy",
            version="1.2.3",
            url="https://example.test",
            released_at=datetime(2026, 5, 7, tzinfo=UTC),
        ),
        Release(
            project="MinorOnly",
            source="github",
            artifact="m",
            version="2.3.0",
            url="https://example.test/m",
            released_at=datetime(2026, 5, 7, tzinfo=UTC),
        ),
    ]
    md = render_markdown(date(2026, 5, 4), rels)
    assert "<summary>Highlights</summary>" not in md


def _minimal_week_html_body_with_highlight(
    *, sort_date: str, kind: str = "major", label: str = "DemoProj"
) -> str:
    return f"""<!DOCTYPE html><html><body><div class="wrap"><main>
<div class="projects">
<details class="project">
<summary>{label}<span class="summary-count"> (1)</span></summary>
<ul class="releases">
<li class="release" data-sort-date="{sort_date}" data-highlight="{kind}"><div class="release-meta"><span class="mono">finos/x</span><span class="sep">|</span><span class="source-tag">github</span><span class="sep">|</span><span class="mono">x</span><span class="sep">|</span><span class="mono">2.0.0</span><span class="sep">|</span><span>—</span><span class="sep">|</span><span>{sort_date}</span><span class="sep">|</span><a class="link" href="https://example/">link</a></div></li>
</ul>
</details>
</div></main></body></html>"""


def test_calendar_rollup_lifts_only_major_highlighted_rows_to_top_section(
    tmp_path: Path,
):
    y = tmp_path / "2026"
    y.mkdir(parents=True)
    # Two majors (different weeks + projects) plus one legacy minor row that
    # must be ignored by the calendar collector.
    (y / "01.html").write_text(
        _minimal_week_html_body_with_highlight(
            sort_date="2026-01-08", kind="major", label="EarlyProj"
        ),
        encoding="utf-8",
    )
    (y / "02.html").write_text(
        _minimal_week_html_body_with_highlight(
            sort_date="2026-01-15", kind="major", label="LateProj"
        ),
        encoding="utf-8",
    )
    (y / "03.html").write_text(
        _minimal_week_html_body_with_highlight(
            sort_date="2026-01-22", kind="minor", label="MinorLegacy"
        ),
        encoding="utf-8",
    )

    write_releases_index(tmp_path)
    cal = (tmp_path / "2026" / "calendar-2026-01.html").read_text(encoding="utf-8")
    # Collapsible highlights block at the top.
    assert '<details class="highlights">' in cal
    assert '<details class="highlights" open' not in cal
    assert "<summary>Highlights" in cal
    # Highlights block appears before the per-project sections.
    assert cal.index('<details class="highlights">') < cal.index(
        '<div class="projects">'
    )
    highlights_chunk = cal.split('<details class="highlights">', 1)[1].split(
        "</details>", 1
    )[0]
    # Earlier major precedes later major (sorted by date ascending).
    assert highlights_chunk.index("2026-01-08") < highlights_chunk.index("2026-01-15")
    # Legacy minor row is NOT lifted.
    assert "2026-01-22" not in highlights_chunk
    assert "MinorLegacy" not in highlights_chunk
    # Each lifted highlight row carries the injected project label.
    assert '<span class="release-project mono">EarlyProj</span>' in highlights_chunk
    assert '<span class="release-project mono">LateProj</span>' in highlights_chunk
    # All three projects still appear in the per-project section below.
    projects_chunk = cal.split('<div class="projects">', 1)[1]
    for proj in ("EarlyProj", "LateProj", "MinorLegacy"):
        assert proj in projects_chunk
    # Per-project rows are NOT augmented with the project label span.
    assert "release-project" not in projects_chunk


def test_calendar_rollup_omits_highlights_when_no_data_highlight_in_sources(
    tmp_path: Path,
):
    y = tmp_path / "2026"
    y.mkdir(parents=True)
    (y / "01.html").write_text(
        _minimal_week_html_body(release_date="2026-01-08"), encoding="utf-8"
    )
    write_releases_index(tmp_path)
    cal = (tmp_path / "2026" / "calendar-2026-01.html").read_text(encoding="utf-8")
    assert '<details class="highlights">' not in cal
