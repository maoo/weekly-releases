from __future__ import annotations

from collections.abc import Iterable

from weekly_releases.landscape import LandscapeIndex


def project_via_shortest_hyphen_prefix_repo(
    landscape: LandscapeIndex,
    finos_repos: frozenset[str],
    repo_slug: str,
) -> str | None:
    """Map e.g. morphir-go → Morphir via shortest finos repo slug that is a strict hyphen-prefix."""
    best: str | None = None
    best_len = 10**9
    for r in finos_repos:
        if len(r) >= len(repo_slug):
            continue
        if repo_slug.startswith(r + "-"):
            p = landscape.project_for_repo(r)
            if p != "Unknown" and len(r) < best_len:
                best_len = len(r)
                best = p
    return best


def pick_github_repo_slug(short_name: str, finos_repos: frozenset[str]) -> str | None:
    """Pick best-matching finos/org repo slug for an artifact or docker image short name."""
    if short_name in finos_repos:
        return short_name
    best: str | None = None
    best_len = -1
    for r in finos_repos:
        if short_name == r or short_name.startswith(r + "-"):
            if len(r) > best_len:
                best = r
                best_len = len(r)
    return best


def _lookup_short_keys(keys: Iterable[str]) -> list[str]:
    shorts: list[str] = []
    for raw in keys:
        k = raw.strip()
        if not k:
            continue
        shorts.append(k)
        if k.startswith("finos/"):
            shorts.append(k.split("/", 1)[1])
        elif "/" in k:
            shorts.append(k.split("/")[-1])
        if k.startswith("@finos/"):
            shorts.append(k.split("/", 1)[1])
    out: list[str] = []
    seen: set[str] = set()
    for s in shorts:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def full_github_name(slug: str | None) -> str | None:
    if not slug:
        return None
    return f"finos/{slug}"


def resolve_project_and_repo(
    landscape: LandscapeIndex,
    finos_repos: frozenset[str],
    lookup_keys: list[str],
    *,
    maven_group_id: str | None = None,
) -> tuple[str, str | None]:
    """Return (project display name, github repo slug without org prefix)."""
    project = "Unknown"
    repo_slug: str | None = None

    for key in lookup_keys:
        p = landscape.project_for_asset(key)
        if p != "Unknown":
            project = p
            repo_slug = landscape.repo_for_asset(key)
            break

    if repo_slug is None:
        for key in lookup_keys:
            repo_slug = landscape.repo_for_asset(key)
            if repo_slug:
                break

    if repo_slug and project == "Unknown":
        project = landscape.project_for_repo(repo_slug)

    if project == "Unknown" or repo_slug is None:
        for short in _lookup_short_keys(lookup_keys):
            cand = pick_github_repo_slug(short, finos_repos)
            if not cand:
                continue
            if repo_slug is None:
                repo_slug = cand
            proj = landscape.project_for_repo(cand)
            if proj != "Unknown":
                project = proj
                break

    if project == "Unknown" and repo_slug:
        proj = landscape.project_for_repo(repo_slug)
        if proj != "Unknown":
            project = proj

    if repo_slug:
        via_prefix = project_via_shortest_hyphen_prefix_repo(
            landscape, finos_repos, repo_slug
        )
        if via_prefix:
            project = via_prefix

    if project == "Unknown" and repo_slug:
        project = repo_slug.replace("-", " ").title()

    if maven_group_id:
        mp = landscape.project_for_maven_group_id(maven_group_id)
        if mp != "Unknown":
            project = mp

    # When we know the GitHub org repo slug, the FINOS landscape ``repo_to_project`` mapping (card
    # ``name`` for any card that lists that repo) overrides heuristics and the title-cased fallback.
    if repo_slug:
        from_landscape = landscape.project_for_repo(repo_slug)
        if from_landscape != "Unknown":
            project = from_landscape

    return project, repo_slug
