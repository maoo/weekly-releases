from datetime import UTC, datetime

from weekly_releases.grouping import (
    MAX_ARTIFACTS_LISTED,
    ReleaseGroup,
    cluster_releases,
    displayed_artifacts,
    major_minor_key,
    release_kind,
    render_group_markdown,
    select_highlight_groups,
)
from weekly_releases.models import Release


def _rel(
    *,
    project: str = "Proj",
    source: str = "maven",
    artifact: str = "a",
    version: str = "1.0.0",
    when: datetime | None = None,
    url: str | None = None,
    github_repo: str | None = "finos/proj",
    publisher: str | None = None,
    description: str | None = None,
) -> Release:
    return Release(
        project=project,
        source=source,
        artifact=artifact,
        version=version,
        url=url or f"https://example.test/{artifact}/{version}",
        released_at=when or datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
        github_repo=github_repo,
        description=description,
        publisher=publisher,
    )


# -- major_minor_key --------------------------------------------------------


def test_major_minor_key_parses_simple_semver():
    assert major_minor_key("1.2.3") == (1, 2)
    assert major_minor_key("0.5.0") == (0, 5)
    assert major_minor_key("4.127.4") == (4, 127)


def test_major_minor_key_strips_leading_v():
    assert major_minor_key("v0.2.0") == (0, 2)
    assert major_minor_key("v10.20.30") == (10, 20)


def test_major_minor_key_handles_prerelease_and_build_tail():
    assert major_minor_key("7.0.0-dev.84") == (7, 0)
    assert major_minor_key("0.5.0-M04-4-eca8df") == (0, 5)
    assert major_minor_key("1.2.3-SNAPSHOT") == (1, 2)


def test_major_minor_key_returns_none_for_non_semver():
    assert major_minor_key("main") is None
    assert major_minor_key("latest") is None
    assert major_minor_key("sha-298ecda") is None
    assert major_minor_key("") is None
    assert major_minor_key("v") is None
    assert major_minor_key("1") is None  # missing minor
    assert major_minor_key("alpha") is None


# -- cluster_releases pass 1 (same project + version + UTC date) -----------


def test_pass1_collapses_same_project_version_date_across_sources():
    a = _rel(source="maven", artifact="org.finos.foo:bar")
    b = _rel(source="maven", artifact="org.finos.foo:baz")
    c = _rel(source="maven", artifact="org.finos.foo:qux")
    d = _rel(source="docker", artifact="finos/foo")
    groups = cluster_releases([a, b, c, d])
    assert len(groups) == 1
    g = groups[0]
    assert isinstance(g, ReleaseGroup)
    assert len(g.members) == 4
    assert g.is_pass1
    assert g.sources == ("maven", "docker")
    assert "org.finos.foo:bar" in g.artifacts
    assert "finos/foo" in g.artifacts


def test_pass1_does_not_collapse_when_version_differs():
    # Different MAJOR.MINOR keeps pass 2 from re-merging them, so the final
    # groups still expose pass-1 behavior.
    a = _rel(version="1.0.0", artifact="x")
    b = _rel(version="2.0.0", artifact="y")
    groups = cluster_releases([a, b])
    assert len(groups) == 2
    assert all(g.is_singleton for g in groups)


def test_pass1_does_not_collapse_when_date_differs():
    # Use unparseable versions so pass 2 cannot collapse them either; this
    # isolates the pass-1 same-date check.
    a = _rel(version="latest", artifact="x", when=datetime(2026, 5, 4, tzinfo=UTC))
    b = _rel(version="latest", artifact="y", when=datetime(2026, 5, 5, tzinfo=UTC))
    groups = cluster_releases([a, b])
    assert len(groups) == 2
    assert all(g.is_singleton for g in groups)


def test_pass1_does_not_collapse_across_projects():
    a = _rel(project="Alpha", version="1.0.0", artifact="x")
    b = _rel(project="Beta", version="1.0.0", artifact="y")
    groups = cluster_releases([a, b])
    assert len(groups) == 2
    assert {g.project for g in groups} == {"Alpha", "Beta"}


def test_pass1_uses_utc_date_not_local():
    early = _rel(
        version="1.0.0",
        artifact="x",
        when=datetime(2026, 5, 5, 23, 30, tzinfo=UTC),
    )
    late = _rel(
        version="1.0.0",
        artifact="y",
        when=datetime(2026, 5, 5, 1, 15, tzinfo=UTC),
    )
    groups = cluster_releases([early, late])
    assert len(groups) == 1
    assert len(groups[0].members) == 2


# -- cluster_releases pass 2 (same MAJOR.MINOR within week) ----------------


def test_pass2_collapses_dev_chain_within_week():
    a = _rel(
        version="7.0.0-dev.84",
        artifact="pkg",
        when=datetime(2026, 5, 4, tzinfo=UTC),
    )
    b = _rel(
        version="7.0.0-dev.85",
        artifact="pkg",
        when=datetime(2026, 5, 6, tzinfo=UTC),
    )
    c = _rel(
        version="7.0.0-dev.86",
        artifact="pkg",
        when=datetime(2026, 5, 8, tzinfo=UTC),
    )
    groups = cluster_releases([a, b, c])
    assert len(groups) == 1
    g = groups[0]
    assert g.is_pass2
    assert len(g.members) == 3
    assert g.versions == ("7.0.0-dev.84", "7.0.0-dev.85", "7.0.0-dev.86")
    assert g.dates == ("2026-05-04", "2026-05-06", "2026-05-08")


def test_pass2_collapses_patch_versions_within_same_minor():
    a = _rel(
        version="4.127.4",
        artifact="x",
        when=datetime(2026, 5, 4, tzinfo=UTC),
    )
    b = _rel(
        version="4.127.5",
        artifact="y",
        when=datetime(2026, 5, 5, tzinfo=UTC),
    )
    groups = cluster_releases([a, b])
    assert len(groups) == 1
    assert groups[0].is_pass2
    assert len(groups[0].members) == 2


def test_pass2_keeps_different_minor_versions_separate():
    a = _rel(
        version="4.127.4",
        artifact="x",
        when=datetime(2026, 5, 4, tzinfo=UTC),
    )
    b = _rel(
        version="4.128.0",
        artifact="y",
        when=datetime(2026, 5, 5, tzinfo=UTC),
    )
    groups = cluster_releases([a, b])
    assert len(groups) == 2
    assert all(g.is_singleton for g in groups)


def test_pass2_skips_unparseable_versions():
    a = _rel(version="main", artifact="x", when=datetime(2026, 5, 4, tzinfo=UTC))
    b = _rel(version="latest", artifact="y", when=datetime(2026, 5, 5, tzinfo=UTC))
    c = _rel(
        version="sha-298ecda",
        artifact="z",
        when=datetime(2026, 5, 6, tzinfo=UTC),
    )
    groups = cluster_releases([a, b, c])
    assert len(groups) == 3
    assert all(g.is_singleton for g in groups)


def test_pass2_uses_pass1_groups_as_input():
    # Two pass-1 groups (each: same version + date, multiple artifacts) sharing 1.2.x.
    a1 = _rel(
        version="1.2.0",
        artifact="alpha",
        when=datetime(2026, 5, 4, tzinfo=UTC),
    )
    a2 = _rel(
        version="1.2.0",
        artifact="beta",
        when=datetime(2026, 5, 4, tzinfo=UTC),
    )
    b1 = _rel(
        version="1.2.1",
        artifact="alpha",
        when=datetime(2026, 5, 6, tzinfo=UTC),
    )
    b2 = _rel(
        version="1.2.1",
        artifact="beta",
        when=datetime(2026, 5, 6, tzinfo=UTC),
    )
    groups = cluster_releases([a1, a2, b1, b2])
    assert len(groups) == 1
    g = groups[0]
    assert g.is_pass2
    assert len(g.members) == 4
    assert g.versions == ("1.2.0", "1.2.1")


def test_pass2_does_not_cluster_across_projects():
    a = _rel(
        project="Alpha",
        version="1.2.0",
        artifact="x",
        when=datetime(2026, 5, 4, tzinfo=UTC),
    )
    b = _rel(
        project="Beta",
        version="1.2.1",
        artifact="y",
        when=datetime(2026, 5, 5, tzinfo=UTC),
    )
    groups = cluster_releases([a, b])
    assert len(groups) == 2


def test_singleton_release_passes_through_unchanged():
    a = _rel(version="1.0.0", artifact="only")
    groups = cluster_releases([a])
    assert len(groups) == 1
    assert groups[0].is_singleton
    assert groups[0].members == (a,)


def test_groups_sorted_by_project_then_earliest_date():
    z = _rel(
        project="Zebra",
        version="1.0.0",
        artifact="z",
        when=datetime(2026, 5, 4, tzinfo=UTC),
    )
    a_late = _rel(
        project="Apple",
        version="1.0.0",
        artifact="a",
        when=datetime(2026, 5, 7, tzinfo=UTC),
    )
    a_early = _rel(
        project="Apple",
        version="2.0.0",
        artifact="a2",
        when=datetime(2026, 5, 5, tzinfo=UTC),
    )
    groups = cluster_releases([z, a_late, a_early])
    # Apple comes before Zebra (case-insensitive); within Apple, earliest first.
    assert [g.project for g in groups] == ["Apple", "Apple", "Zebra"]
    apple_dates = [g.sort_date_iso for g in groups[:2]]
    assert apple_dates == sorted(apple_dates)


# -- ReleaseGroup helpers --------------------------------------------------


def test_release_group_publishers_merged_unique_case_insensitive():
    a = _rel(artifact="a", publisher="Ada")
    b = _rel(artifact="b", publisher="ada")
    c = _rel(artifact="c", publisher="Babbage")
    g = cluster_releases([a, b, c])[0]
    # Order: first-seen, case-insensitive dedupe.
    assert g.publishers_merged == "Ada, Babbage"


def test_release_group_description_first_nonempty_wins():
    a = _rel(artifact="a", description=None)
    b = _rel(artifact="b", description="")
    c = _rel(artifact="c", description="actual text")
    d = _rel(artifact="d", description="other text")
    g = cluster_releases([a, b, c, d])[0]
    assert g.description_first_nonempty == "actual text"


def test_release_group_github_repo_collapses_when_unique():
    a = _rel(artifact="a", github_repo="finos/proj")
    b = _rel(artifact="b", github_repo="finos/proj")
    g = cluster_releases([a, b])[0]
    assert g.github_repo_or_none == "finos/proj"


def test_release_group_github_repo_none_when_mixed():
    a = _rel(artifact="a", github_repo="finos/one")
    b = _rel(artifact="b", github_repo="finos/two")
    g = cluster_releases([a, b])[0]
    assert g.github_repo_or_none is None


# -- render_group_markdown -------------------------------------------------


def test_render_group_markdown_singleton_matches_release_line():
    a = _rel(
        artifact="repo",
        version="v1",
        when=datetime(2026, 1, 8, tzinfo=UTC),
        url="https://example.test",
        github_repo=None,
        publisher=None,
    )
    g = cluster_releases([a])[0]
    out = render_group_markdown(g)
    # Same shape as the historical Release.as_markdown_line(omit_project=True).
    assert out == a.as_markdown_line(omit_project=True)


def test_render_group_markdown_pass1_has_artifact_count_and_compact_summary_line():
    a = _rel(
        source="maven",
        artifact="org.finos.foo:bar",
        version="1.2.0",
        when=datetime(2026, 5, 5, tzinfo=UTC),
        url="https://example.test/bar",
    )
    b = _rel(
        source="maven",
        artifact="org.finos.foo:baz",
        version="1.2.0",
        when=datetime(2026, 5, 5, tzinfo=UTC),
        url="https://example.test/baz",
    )
    c = _rel(
        source="docker",
        artifact="finos/foo",
        version="1.2.0",
        when=datetime(2026, 5, 5, tzinfo=UTC),
        url="https://example.test/docker-foo",
    )
    g = cluster_releases([a, b, c])[0]
    out = render_group_markdown(g)
    lines = out.splitlines()
    # Header bullet contains the count phrase and shared version + date.
    assert lines[0].startswith("- ")
    assert "**3 artifacts**" in lines[0]
    assert "`1.2.0`" in lines[0]
    assert "2026-05-05" in lines[0]
    assert "multiple" in lines[0]
    # Exactly one indented summary line follows (no per-member sub-bullets).
    sub = [line for line in lines[1:] if line.startswith("  - ")]
    assert len(sub) == 1
    summary = sub[0]
    assert summary.startswith(
        "  - Artifacts: `org.finos.foo:bar`, `org.finos.foo:baz`, `finos/foo`"
    )
    assert " | Versions: `1.2.0`" in summary
    # Per-member dates are NOT repeated — already shown in the meta date column.
    assert "2026-05-05" not in summary
    # Link points to the latest member (== last entry of members_sorted).
    last_url = g.members_sorted[-1].url
    assert summary.endswith(f"| Link: [link]({last_url})")


def test_render_group_markdown_pass2_has_release_count_and_version_range():
    a = _rel(
        artifact="pkg",
        version="7.0.0-dev.84",
        when=datetime(2026, 5, 4, tzinfo=UTC),
        url="https://example.test/dev84",
    )
    b = _rel(
        artifact="pkg",
        version="7.0.0-dev.85",
        when=datetime(2026, 5, 6, tzinfo=UTC),
        url="https://example.test/dev85",
    )
    c = _rel(
        artifact="pkg",
        version="7.0.0-dev.86",
        when=datetime(2026, 5, 8, tzinfo=UTC),
        url="https://example.test/dev86",
    )
    g = cluster_releases([a, b, c])[0]
    out = render_group_markdown(g)
    lines = out.splitlines()
    assert "**3 releases**" in lines[0]
    assert "7.0.0-dev.84 → 7.0.0-dev.86" in lines[0]
    assert "2026-05-04 → 2026-05-08" in lines[0]
    sub = [line for line in lines[1:] if line.startswith("  - ")]
    assert len(sub) == 1
    summary = sub[0]
    # Distinct artifacts (single one here) + distinct versions (three).
    assert "Artifacts: `pkg`" in summary
    assert "Versions: `7.0.0-dev.84`, `7.0.0-dev.85`, `7.0.0-dev.86`" in summary
    # Link points at the latest release (dev.86 on 2026-05-08).
    assert summary.endswith("| Link: [link](https://example.test/dev86)")


def test_render_group_markdown_emits_first_description():
    a = _rel(artifact="a", version="1.0.0", description=None)
    b = _rel(artifact="b", version="1.0.0", description="hello world")
    g = cluster_releases([a, b])[0]
    out = render_group_markdown(g)
    assert "Description: hello world" in out


# -- displayed_artifacts (artifact-list cap) -------------------------------


def test_max_artifacts_listed_default_is_twenty():
    assert MAX_ARTIFACTS_LISTED == 20


def test_displayed_artifacts_returns_full_list_when_at_or_below_cap():
    when = datetime(2026, 5, 5, tzinfo=UTC)
    rels = [
        _rel(artifact=f"art-{i:02d}", version="1.0.0", when=when) for i in range(20)
    ]
    g = cluster_releases(rels)[0]
    visible, hidden = displayed_artifacts(g)
    assert hidden == 0
    # No truncation => preserve the input (first-seen) order.
    assert list(visible) == [f"art-{i:02d}" for i in range(20)]


def test_displayed_artifacts_picks_twenty_shortest_when_over_cap():
    when = datetime(2026, 5, 5, tzinfo=UTC)
    # 19 SHORT names (3 chars each) + 5 LONG names (>3 chars). Total = 24 > 20.
    short_names = [f"s{i:02d}" for i in range(19)]
    long_names = ["really-long-artifact-name-" + str(i) for i in range(5)]
    rels = [
        _rel(artifact=name, version="1.0.0", when=when)
        for name in short_names + long_names
    ]
    g = cluster_releases(rels)[0]
    visible, hidden = displayed_artifacts(g)
    assert hidden == 4  # 24 total - 20 shown
    assert len(visible) == 20
    # All 19 short names made the cut.
    for name in short_names:
        assert name in visible
    # Exactly one long name (the lexicographically first among ties on length)
    # filled slot 20.
    long_in_visible = [n for n in visible if n in long_names]
    assert len(long_in_visible) == 1
    assert long_in_visible[0] == sorted(long_names)[0]
    # Visible list is ordered shortest-first (ties broken alphabetically).
    sorted_pairs = sorted([(len(n), n) for n in visible])
    assert [n for _, n in sorted_pairs] == list(visible)


def test_displayed_artifacts_breaks_length_ties_alphabetically():
    when = datetime(2026, 5, 5, tzinfo=UTC)
    # 21 names, all the same length, asking for the first 20 => the LAST one
    # alphabetically must be the one cut.
    names = [f"x-{i:02d}" for i in range(21)]
    rels = [_rel(artifact=n, version="1.0.0", when=when) for n in names]
    g = cluster_releases(rels)[0]
    visible, hidden = displayed_artifacts(g)
    assert hidden == 1
    cut = set(names) - set(visible)
    assert cut == {sorted(names)[-1]}


def test_render_group_markdown_truncates_artifact_list_with_more_suffix():
    when = datetime(2026, 5, 5, tzinfo=UTC)
    short_names = [f"s{i:02d}" for i in range(19)]
    long_names = ["really-long-artifact-name-" + str(i) for i in range(5)]
    rels = [
        _rel(artifact=n, version="1.0.0", when=when) for n in short_names + long_names
    ]
    g = cluster_releases(rels)[0]
    out = render_group_markdown(g)
    summary = next(
        line for line in out.splitlines() if line.startswith("  - Artifacts:")
    )
    # Truncation hint: explicit "(+M more)" suffix where M = total - 20.
    assert " (+4 more)" in summary
    # Long names that exceed the cap (only the lexicographically first of the
    # length-tied long names is kept) do not all appear.
    cut_long = sorted(long_names)[1:]
    for name in cut_long:
        assert f"`{name}`" not in summary
    # All short names ARE present.
    for name in short_names:
        assert f"`{name}`" in summary
    # The meta-row count phrase still reports the TRUE artifact count, not 20.
    assert "**24 artifacts**" in out


# -- release_kind ----------------------------------------------------------


def test_release_kind_major():
    assert release_kind("2.0.0") == "major"
    assert release_kind("v1.0.0") == "major"
    assert release_kind("0.0.0") == "major"
    assert release_kind("10.0.0") == "major"
    assert release_kind("3.0.0.0") == "major"


def test_release_kind_minor():
    assert release_kind("2.3.0") == "minor"
    assert release_kind("0.5.0") == "minor"
    assert release_kind("v1.4.0") == "minor"
    assert release_kind("1.4.0.0") == "minor"


def test_release_kind_rejects_patch_versions():
    assert release_kind("1.2.3") is None
    assert release_kind("4.127.4") is None
    assert release_kind("v0.2.1") is None


def test_release_kind_rejects_prerelease_or_build_metadata():
    assert release_kind("1.0.0-dev.84") is None
    assert release_kind("7.0.0-dev.84") is None
    assert release_kind("2.0.0-rc.1") is None
    assert release_kind("2.0.0-beta") is None
    assert release_kind("2.0.0-SNAPSHOT") is None
    assert release_kind("0.5.0-M04-4-eca8df") is None
    assert release_kind("1.0.0+build.1") is None


def test_release_kind_rejects_unparseable_or_too_short():
    assert release_kind("") is None
    assert release_kind("main") is None
    assert release_kind("latest") is None
    assert release_kind("sha-298ecda") is None
    assert release_kind("v") is None
    assert release_kind("1.0") is None  # require at least 3 components
    assert release_kind("1") is None
    assert release_kind("not.a.number") is None


# -- ReleaseGroup.highlight_kind -------------------------------------------


def test_highlight_kind_singleton_major():
    g = cluster_releases([_rel(version="2.0.0")])[0]
    assert g.highlight_kind == "major"


def test_highlight_kind_singleton_minor_is_not_highlighted():
    # Minor releases (X.Y.0 with Y>0) classify as ``minor`` via release_kind
    # but are intentionally NOT surfaced as highlights.
    g = cluster_releases([_rel(version="2.3.0")])[0]
    assert g.highlight_kind is None


def test_highlight_kind_singleton_none_for_patch():
    g = cluster_releases([_rel(version="2.3.1")])[0]
    assert g.highlight_kind is None


def test_highlight_kind_pass1_minor_only_group_is_not_highlighted():
    when = datetime(2026, 5, 5, tzinfo=UTC)
    members = [
        _rel(artifact="a", version="2.3.0", when=when),
        _rel(artifact="b", version="2.3.0", when=when),
    ]
    g = cluster_releases(members)[0]
    assert g.is_pass1
    assert g.highlight_kind is None


def test_highlight_kind_pass2_group_with_any_major_member():
    members = [
        _rel(
            artifact="x", version="7.0.0-dev.84", when=datetime(2026, 5, 4, tzinfo=UTC)
        ),
        _rel(artifact="y", version="7.0.0", when=datetime(2026, 5, 6, tzinfo=UTC)),
    ]
    g = cluster_releases(members)[0]
    assert g.is_pass2
    # 7.0.0 is a major release, even though 7.0.0-dev.84 is not.
    assert g.highlight_kind == "major"


def test_highlight_kind_mixed_major_minor_group_keeps_major():
    # ``cluster_releases`` cannot naturally produce a major+minor mix (a major
    # requires MINOR=0 and a minor requires MINOR>0, so the two land in
    # different MAJOR.MINOR buckets). Construct ``ReleaseGroup`` directly to
    # exercise the "any major member ⇒ highlight" rule on a hand-rolled
    # mixed group.
    members = (
        _rel(artifact="x", version="2.3.0", when=datetime(2026, 5, 4, tzinfo=UTC)),
        _rel(artifact="y", version="2.0.0", when=datetime(2026, 5, 5, tzinfo=UTC)),
    )
    g = ReleaseGroup(members=members, kind="series")
    assert g.highlight_kind == "major"


def test_highlight_kind_none_when_group_only_has_minor_and_prereleases():
    # Even though one member is "minor" classification, minors are no longer
    # highlighted, so the group's highlight_kind is None.
    members = [
        _rel(
            artifact="x", version="7.0.0-dev.84", when=datetime(2026, 5, 4, tzinfo=UTC)
        ),
        _rel(artifact="y", version="2.3.0", when=datetime(2026, 5, 5, tzinfo=UTC)),
    ]
    # These two land in different MAJOR.MINOR buckets so build the group by hand.
    g = ReleaseGroup(members=tuple(members), kind="series")
    assert g.highlight_kind is None


def test_highlight_kind_none_when_group_only_has_prereleases_and_patches():
    members = [
        _rel(
            artifact="x", version="7.0.0-dev.84", when=datetime(2026, 5, 4, tzinfo=UTC)
        ),
        _rel(
            artifact="y", version="7.0.0-dev.85", when=datetime(2026, 5, 6, tzinfo=UTC)
        ),
    ]
    g = cluster_releases(members)[0]
    assert g.highlight_kind is None


# -- select_highlight_groups -----------------------------------------------


def test_select_highlight_groups_keeps_only_majors_ordered_by_earliest_date():
    g_minor = cluster_releases(
        [_rel(project="P1", version="2.3.0", when=datetime(2026, 5, 8, tzinfo=UTC))]
    )[0]
    g_major_late = cluster_releases(
        [_rel(project="P2", version="3.0.0", when=datetime(2026, 5, 8, tzinfo=UTC))]
    )[0]
    g_major_early = cluster_releases(
        [_rel(project="P3", version="2.0.0", when=datetime(2026, 5, 4, tzinfo=UTC))]
    )[0]
    g_patch = cluster_releases(
        [_rel(project="P4", version="2.3.1", when=datetime(2026, 5, 5, tzinfo=UTC))]
    )[0]

    selected = select_highlight_groups([g_minor, g_patch, g_major_late, g_major_early])

    # Minor + patch dropped; majors ordered by earliest released_at.
    assert [g.project for g in selected] == ["P3", "P2"]
    assert [g.highlight_kind for g in selected] == ["major", "major"]


def test_select_highlight_groups_returns_empty_when_only_minors_or_patches():
    g_patch = cluster_releases([_rel(version="1.2.3")])[0]
    g_pre = cluster_releases([_rel(version="2.0.0-rc.1")])[0]
    g_minor = cluster_releases([_rel(version="2.3.0")])[0]
    assert select_highlight_groups([g_patch, g_pre, g_minor]) == []
