from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from weekly_releases.models import Release

# Pre-release suffix and PATCH may differ within a pass-2 cluster — only the
# leading MAJOR.MINOR pair (with an optional ``v``) decides membership.
_MAJOR_MINOR_RE = re.compile(r"^v?(\d+)\.(\d+)")

# Highlights detection requires a stricter parse than ``major_minor_key``: the
# version must be a clean dotted integer triple (or longer) with no pre-release
# or build-metadata tail and a zero PATCH.
_FULL_DOTTED_RE = re.compile(r"^v?(\d+(?:\.\d+)+)$")

# Maximum number of distinct artifact names rendered inline in a grouped row.
# When a group exceeds this, ``displayed_artifacts`` keeps the 20 SHORTEST
# names (ties broken alphabetically) and renderers append a ``(+M more)``
# suffix. The meta-row "N artifacts" count phrase always reflects the true
# member count, regardless of truncation.
MAX_ARTIFACTS_LISTED = 20

T = TypeVar("T")


def major_minor_key(version: str) -> tuple[int, int] | None:
    """Return the ``(MAJOR, MINOR)`` tuple a version begins with, or ``None``.

    Versions like ``main``, ``latest`` or ``sha-298ecda`` return ``None`` and are
    excluded from the second clustering pass.
    """
    if not version:
        return None
    m = _MAJOR_MINOR_RE.match(version.strip())
    if m is None:
        return None
    return int(m.group(1)), int(m.group(2))


def release_kind(version: str) -> str | None:
    """Return ``"major"`` for ``X.0.0``, ``"minor"`` for ``X.Y.0`` (Y > 0), else ``None``.

    A version qualifies as a highlight only when, after stripping an optional
    leading ``v``, it has no ``-`` or ``+`` suffix (so any pre-release or
    build-metadata tail disqualifies it), splits into **at least three** dotted
    components that all parse as non-negative integers, and every component
    after MAJOR.MINOR is exactly ``0``. Reuses the same leading-digits parsing
    primitive as :func:`major_minor_key`.
    """
    if not version:
        return None
    s = version.strip()
    if not s:
        return None
    m = _FULL_DOTTED_RE.match(s)
    if m is None:
        return None
    parts = m.group(1).split(".")
    if len(parts) < 3:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if any(n < 0 for n in nums):
        return None
    # PATCH and any later components must all be zero.
    if any(n != 0 for n in nums[2:]):
        return None
    _major, minor = nums[0], nums[1]
    return "major" if minor == 0 else "minor"


def _utc_date_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).date().isoformat()


def _ordered_unique(
    items: Iterable[T], *, key: Callable[[T], object] | None = None
) -> list[T]:
    seen: set[object] = set()
    out: list[T] = []
    for it in items:
        k: object = key(it) if key is not None else it
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


@dataclass(frozen=True, slots=True)
class ReleaseGroup:
    """One rendered row: either a singleton release or a clustered set."""

    members: tuple[Release, ...]
    # Cluster pass that produced this group:
    #   ``"single"``   one underlying release
    #   ``"exact"``    pass-1 cluster (project + version + UTC date)
    #   ``"series"``   pass-2 cluster (project + MAJOR.MINOR series)
    kind: str = "single"

    # -- identity ----------------------------------------------------------

    @property
    def project(self) -> str:
        return self.members[0].project

    @property
    def is_singleton(self) -> bool:
        return len(self.members) == 1

    @property
    def is_pass1(self) -> bool:
        return self.kind == "exact" and not self.is_singleton

    @property
    def is_pass2(self) -> bool:
        return self.kind == "series" and not self.is_singleton

    # -- ordering helpers --------------------------------------------------

    @property
    def sort_datetime(self) -> datetime:
        return min(m.released_at for m in self.members)

    @property
    def sort_date_iso(self) -> str:
        return _utc_date_iso(self.sort_datetime)

    @property
    def members_sorted(self) -> tuple[Release, ...]:
        """Members ordered by (released_at, artifact) for sub-bullet emission."""
        return tuple(sorted(self.members, key=lambda r: (r.released_at, r.artifact)))

    # -- aggregated views --------------------------------------------------

    @property
    def sources(self) -> tuple[str, ...]:
        """Distinct source ids in input order."""
        return tuple(_ordered_unique([m.source for m in self.members]))

    @property
    def artifacts(self) -> tuple[str, ...]:
        """Distinct artifact identifiers in input order."""
        return tuple(_ordered_unique([m.artifact for m in self.members]))

    @property
    def versions(self) -> tuple[str, ...]:
        """Distinct versions in date-ascending order (for ``min → max`` labels)."""
        return tuple(_ordered_unique([m.version for m in self.members_sorted]))

    @property
    def dates(self) -> tuple[str, ...]:
        """Distinct UTC release dates in ascending order."""
        return tuple(
            _ordered_unique([_utc_date_iso(m.released_at) for m in self.members_sorted])
        )

    @property
    def publishers_merged(self) -> str | None:
        """Comma-separated unique publishers, case-insensitive, first-seen order."""
        labels: list[str] = []
        for m in self.members:
            if not m.publisher:
                continue
            for chunk in m.publisher.split(","):
                value = chunk.strip()
                if not value:
                    continue
                labels.append(value)
        if not labels:
            return None
        unique = _ordered_unique(labels, key=lambda v: v.casefold())
        return ", ".join(unique)

    @property
    def github_repo_or_none(self) -> str | None:
        """The shared GitHub repo when every member agrees, else ``None``."""
        repos = _ordered_unique([m.github_repo for m in self.members if m.github_repo])
        if len(repos) == 1:
            return repos[0]
        return None

    @property
    def description_first_nonempty(self) -> str | None:
        for m in self.members:
            if m.description and m.description.strip():
                return m.description
        return None

    @property
    def version_label(self) -> str:
        vs = self.versions
        if len(vs) == 1:
            return vs[0]
        return f"{vs[0]} → {vs[-1]}"

    @property
    def date_label(self) -> str:
        ds = self.dates
        if len(ds) == 1:
            return ds[0]
        return f"{ds[0]} → {ds[-1]}"

    @property
    def highlight_kind(self) -> str | None:
        """``"major"`` if any member is a major release (``X.0.0``), else ``None``.

        Minor releases (``X.Y.0`` with ``Y > 0``) classify as ``"minor"`` via
        :func:`release_kind` but are intentionally **not** highlighted —
        only top-of-version major bumps qualify for the top-of-page Highlights
        block and the calendar rollup.
        """
        for m in self.members:
            if release_kind(m.version) == "major":
                return "major"
        return None


def cluster_releases(rels: Sequence[Release]) -> list[ReleaseGroup]:
    """Reduce raw releases to ordered ``ReleaseGroup`` rows for rendering.

    Pass 1: collapse rows with identical ``(project, version, UTC date)``
    (source-agnostic). Pass 2: collapse the resulting groups within a project
    that share the same ``MAJOR.MINOR`` version prefix. The date-window check
    is implicit because rendering operates on a single ISO week.
    """
    if not rels:
        return []

    # ---- Pass 1: (project, version, UTC date) ---------------------------
    pass1_buckets: dict[tuple[str, str, str], list[Release]] = {}
    pass1_order: list[tuple[str, str, str]] = []
    for rel in rels:
        key = (rel.project, rel.version, _utc_date_iso(rel.released_at))
        if key not in pass1_buckets:
            pass1_buckets[key] = []
            pass1_order.append(key)
        pass1_buckets[key].append(rel)

    pass1_groups: list[ReleaseGroup] = []
    for key in pass1_order:
        members = tuple(pass1_buckets[key])
        kind = "exact" if len(members) > 1 else "single"
        pass1_groups.append(ReleaseGroup(members=members, kind=kind))

    # ---- Pass 2: (project, MAJOR.MINOR series) --------------------------
    pass2_buckets: dict[tuple[str, tuple[int, int]], list[ReleaseGroup]] = {}
    pass2_order: list[tuple[str, tuple[int, int]]] = []
    final: list[ReleaseGroup] = []
    for g in pass1_groups:
        # Members of a pass-1 group all share the same version, so any one
        # member is enough to derive the MAJOR.MINOR key.
        sample_version = g.members[0].version
        mm = major_minor_key(sample_version)
        if mm is None:
            final.append(g)
            continue
        key2 = (g.project, mm)
        if key2 not in pass2_buckets:
            pass2_buckets[key2] = []
            pass2_order.append(key2)
        pass2_buckets[key2].append(g)

    for key2 in pass2_order:
        candidate_groups = pass2_buckets[key2]
        if len(candidate_groups) == 1:
            final.append(candidate_groups[0])
            continue
        merged: list[Release] = []
        for sub in candidate_groups:
            merged.extend(sub.members)
        final.append(ReleaseGroup(members=tuple(merged), kind="series"))

    final.sort(
        key=lambda group: (group.project.casefold(), group.project, group.sort_datetime)
    )
    return final


# -- Highlight selection ---------------------------------------------------


def select_highlight_groups(groups: Sequence[ReleaseGroup]) -> list[ReleaseGroup]:
    """Filter groups to those carrying a highlight kind, ordered for display.

    Only **major** releases are highlighted. Selected groups are sorted by
    earliest ``released_at`` ascending and then by project name
    (case-insensitive).
    """
    highlighted = [g for g in groups if g.highlight_kind is not None]
    return sorted(
        highlighted,
        key=lambda g: (g.sort_datetime, g.project.casefold()),
    )


# -- Markdown rendering ----------------------------------------------------


def _group_count_phrase(group: ReleaseGroup) -> str:
    if group.is_pass1:
        return f"**{len(group.members)} artifacts**"
    return f"**{len(group.members)} releases**"


def displayed_artifacts(group: ReleaseGroup) -> tuple[tuple[str, ...], int]:
    """Return ``(visible, hidden_count)`` for a grouped row's artifact list.

    When ``len(group.artifacts) <= MAX_ARTIFACTS_LISTED`` the full list is
    returned in the original (first-seen) order with a hidden count of ``0``.
    When the list exceeds the cap, the helper picks the **20 shortest** names
    sorted by length ascending (ties broken alphabetically), so wide groups
    stay readable. The second tuple element is ``len(group.artifacts) - 20``
    so renderers can append a ``(+M more)`` truncation hint.
    """
    artifacts = group.artifacts
    if len(artifacts) <= MAX_ARTIFACTS_LISTED:
        return (artifacts, 0)
    by_length = sorted(artifacts, key=lambda a: (len(a), a))
    visible = tuple(by_length[:MAX_ARTIFACTS_LISTED])
    hidden = len(artifacts) - MAX_ARTIFACTS_LISTED
    return (visible, hidden)


def render_group_markdown(group: ReleaseGroup, *, include_project: bool = False) -> str:
    """Render a single ``ReleaseGroup`` as one or more Markdown lines.

    Singletons keep the historical ``Release.as_markdown_line`` shape. Multi-
    member groups emit one header bullet plus a single indented summary line:
    ``- Artifacts: <…> | Versions: <…> | Link: [link](<latest member URL>)``.
    Per-member dates are intentionally omitted because the date timeframe is
    already encoded in the header bullet's ``date_label`` column.

    When ``include_project=True`` the project label is prepended as a leading
    column (used by the top-of-page Highlights block, where there is no
    enclosing project section to imply the project name).
    """
    if group.is_singleton:
        return group.members[0].as_markdown_line(omit_project=not include_project)

    gh = group.github_repo_or_none
    gh_str = f"`{gh}`" if gh else "—"
    sources = ", ".join(group.sources)
    publishers = group.publishers_merged or "—"
    artifact_label = _group_count_phrase(group)
    project_prefix = f"`{group.project}` | " if include_project else ""
    header = (
        f"- {project_prefix}{gh_str} | {sources} | {artifact_label} | "
        f"`{group.version_label}` | {publishers} | {group.date_label} | multiple"
    )
    body: list[str] = [header]
    desc = group.description_first_nonempty
    if desc:
        body.append(f"  - Description: {desc}")
    visible_artifacts, hidden = displayed_artifacts(group)
    artifacts_md = ", ".join(f"`{a}`" for a in visible_artifacts)
    if hidden:
        artifacts_md = f"{artifacts_md} (+{hidden} more)"
    versions_md = ", ".join(f"`{v}`" for v in group.versions)
    last_url = group.members_sorted[-1].url
    body.append(
        f"  - Artifacts: {artifacts_md} | Versions: {versions_md} | "
        f"Link: [link]({last_url})"
    )
    return "\n".join(body)
