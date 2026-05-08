from datetime import datetime, timezone, date
from pathlib import Path

from weekly_releases.models import Release
from weekly_releases.storage import latest_weekly_file, render_markdown, write_weekly_file


def test_render_markdown_with_and_without_releases():
    empty = render_markdown(date(2026, 1, 8), [])
    assert "No releases found" in empty

    release = Release(
        project="Proj",
        source="github",
        artifact="repo",
        version="v1",
        url="https://example.test",
        released_at=datetime(2026, 1, 8, tzinfo=timezone.utc),
    )
    full = render_markdown(date(2026, 1, 8), [release])
    assert "## Proj" in full
    assert "`Proj` |" not in full  # project shown only in heading when grouped
    assert " — " in full
    assert "[link](https://example.test)" in full

    with_desc = Release(
        project="Proj",
        source="github",
        artifact="repo",
        version="v1",
        url="https://example.test",
        released_at=datetime(2026, 1, 8, tzinfo=timezone.utc),
        description="Ships the initial API.",
    )
    md = render_markdown(date(2026, 1, 8), [with_desc])
    assert "## Proj" in md
    assert "Description: Ships the initial API." in md


def test_render_markdown_groups_projects_sorted_and_omits_duplicate_label():
    early = Release(
        project="Zebra",
        source="github",
        artifact="z",
        version="1",
        url="https://z.test",
        released_at=datetime(2026, 1, 7, tzinfo=timezone.utc),
    )
    late_same = Release(
        project="Zebra",
        source="docker",
        artifact="finos/z",
        version="2",
        url="https://hub.docker.com/r/finos/z/tags",
        released_at=datetime(2026, 1, 9, tzinfo=timezone.utc),
    )
    apple = Release(
        project="Apple",
        source="github",
        artifact="a",
        version="1",
        url="https://a.test",
        released_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )
    md = render_markdown(date(2026, 1, 8), [early, apple, late_same])
    assert md.index("## Apple") < md.index("## Zebra")
    zebra_section = md.split("## Zebra", 1)[1].split("##", 1)[0]
    assert zebra_section.index("docker") > zebra_section.index("github")
    assert "`Zebra` |" not in md


def test_write_and_find_latest(tmp_path: Path):
    rel = Release(
        project="Proj",
        source="npm",
        artifact="pkg",
        version="1.0.0",
        url="https://example.test/pkg",
        released_at=datetime(2026, 1, 8, tzinfo=timezone.utc),
    )
    out = write_weekly_file(tmp_path, date(2026, 1, 8), [rel])
    assert out.exists()
    latest = latest_weekly_file(tmp_path)
    assert latest == out

