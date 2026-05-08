from weekly_releases.landscape import LandscapeIndex
from weekly_releases.resolution import (
    pick_github_repo_slug,
    resolve_project_and_repo,
)


def test_pick_github_repo_slug_prefers_longest_prefix():
    repos = frozenset({"legend", "legend-engine"})
    assert pick_github_repo_slug("legend-engine-server", repos) == "legend-engine"
    assert pick_github_repo_slug("legend-studio", repos) == "legend"


def test_resolve_morphir_go_via_hyphen_prefix_when_not_in_landscape_assets():
    idx = LandscapeIndex(repo_to_project={"morphir": "Morphir"})
    project, slug = resolve_project_and_repo(
        idx, frozenset({"morphir", "morphir-go"}), ["morphir-go"]
    )
    assert slug == "morphir-go"
    assert project == "Morphir"


def test_resolve_finds_project_via_org_slug_match():
    idx = LandscapeIndex(repo_to_project={"legend-studio": "Legend"})
    project, slug = resolve_project_and_repo(
        idx, frozenset({"legend-studio"}), ["finos/legend-studio"]
    )
    assert project == "Legend"
    assert slug == "legend-studio"
