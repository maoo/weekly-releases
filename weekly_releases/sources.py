from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from weekly_releases.description_text import normalize_release_description
from weekly_releases.github_auth import github_api_headers
from weekly_releases.landscape import LandscapeIndex
from weekly_releases.models import Release, format_publisher_label
from weekly_releases.resolution import full_github_name, resolve_project_and_repo

# Solr ``core=gav`` ``timestamp`` window is widened backward so laggy indexing still surfaces
# candidates; release times are still taken from deps.dev (per-version ``publishedAt``).
MAVEN_SOLR_DISCOVERY_BUFFER_DAYS = 14
# If Solr returns more raw rows than this, fall back to the legacy per-coordinate scan to avoid
# tens of thousands of deps.dev GetVersion calls in one run.
MAVEN_SOLR_GAV_MAX_RAW_HITS = 25_000
MAVEN_PARENT_CHAIN_MAX_DEPTH = 6


def maven_solr_gav_timestamp_bounds(
    start: datetime,
    end: datetime,
    *,
    buffer_days: int = MAVEN_SOLR_DISCOVERY_BUFFER_DAYS,
) -> tuple[int, int]:
    """Milliseconds ``[lower, upper]`` for Solr ``timestamp`` range queries (``core=gav``)."""
    lower = start - timedelta(days=buffer_days)
    lower_ms = int(lower.timestamp() * 1000)
    upper_ms = int(end.timestamp() * 1000)
    return lower_ms, upper_ms


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _in_range(ts: datetime, start: datetime, end: datetime) -> bool:
    return start <= ts <= end


def _maven_pom_url(group_id: str, artifact: str, version: str) -> str:
    """Central Repository path: group dots become directories."""
    rel = (
        "/".join(group_id.split("."))
        + f"/{quote(artifact, safe='.-_')}/{quote(version, safe='.-_')}/{artifact}-{version}.pom"
    )
    return f"https://repo1.maven.org/maven2/{rel}"


def _maven_search_artifact_url(group_id: str, artifact: str, version: str) -> str:
    g = quote(group_id, safe=".")
    a = quote(artifact, safe=".")
    v = quote(version, safe=".")
    return f"https://search.maven.org/artifact/{g}/{a}/{v}/jar"


def _maven_pom_text(
    client: httpx.Client, group_id: str, artifact: str, version: str
) -> str | None:
    url = _maven_pom_url(group_id, artifact, version)
    try:
        resp = client.get(url)
        if resp.status_code != 200:
            return None
        return resp.text
    except httpx.HTTPError:
        return None


def _maven_description_from_pom_text(text: str) -> str | None:
    m = re.search(r"<description>\s*(.*?)\s*</description>", text, re.DOTALL)
    if not m:
        return None
    inner = m.group(1).strip()
    if inner.startswith("<![CDATA[") and inner.endswith("]]>"):
        inner = inner[9:-3].strip()
    return inner or None


def _maven_xml_text_inner(block: str, tag: str) -> str | None:
    xm = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.IGNORECASE | re.DOTALL)
    if not xm:
        return None
    raw = xm.group(1).strip()
    if raw.startswith("<![CDATA[") and raw.endswith("]]>"):
        raw = raw[9:-3].strip()
    raw = re.sub(r"\s+", " ", raw)
    return raw or None


def _maven_developer_labels_from_pom_text(pom_text: str) -> list[str]:
    """All ``<developer>`` entries under ``<developers>`` as ``format_publisher_label(name, id)``."""
    labels: list[str] = []
    m = re.search(
        r"<developers[^>]*>(.*?)</developers>", pom_text, re.IGNORECASE | re.DOTALL
    )
    if not m:
        return labels
    inner = m.group(1)
    for dm in re.finditer(
        r"<developer[^>]*>(.*?)</developer>", inner, re.IGNORECASE | re.DOTALL
    ):
        block = dm.group(1)
        name = _maven_xml_text_inner(block, "name")
        did = _maven_xml_text_inner(block, "id")
        lab = format_publisher_label(name, did)
        if lab:
            labels.append(lab)
    return labels


def _maven_parent_coordinates_from_pom(pom_text: str) -> tuple[str, str, str] | None:
    """Return ``(groupId, artifactId, version)`` from the first ``<parent>`` block, if complete."""
    pm = re.search(r"<parent[^>]*>(.*?)</parent>", pom_text, re.IGNORECASE | re.DOTALL)
    if not pm:
        return None
    block = pm.group(1)
    gid = _maven_xml_text_inner(block, "groupId")
    aid = _maven_xml_text_inner(block, "artifactId")
    ver = _maven_xml_text_inner(block, "version")
    if not gid or not aid or not ver:
        return None
    if ver.startswith("${") and ver.endswith("}"):
        return None
    return gid, aid, ver


def _maven_contributors_label(
    client: httpx.Client,
    group_id: str,
    artifact_id: str,
    version: str,
    *,
    leaf_pom_text: str | None = None,
) -> str | None:
    """Developer names from the artifact POM and its ``<parent>`` chain (Maven Central)."""
    seen_coords: set[tuple[str, str, str]] = set()
    ordered: list[str] = []
    seen_cf: set[str] = set()
    g, a, v = group_id, artifact_id, version
    leaf_key = (group_id, artifact_id, version)
    for _ in range(MAVEN_PARENT_CHAIN_MAX_DEPTH):
        coord = (g, a, v)
        if coord in seen_coords:
            break
        seen_coords.add(coord)
        if leaf_pom_text is not None and coord == leaf_key:
            text = leaf_pom_text
        else:
            text = _maven_pom_text(client, g, a, v)
        if not text:
            break
        for lab in _maven_developer_labels_from_pom_text(text):
            cf = lab.casefold()
            if cf not in seen_cf:
                seen_cf.add(cf)
                ordered.append(lab)
        parent = _maven_parent_coordinates_from_pom(text)
        if not parent:
            break
        g, a, v = parent
    return ", ".join(ordered) if ordered else None


def _maven_pom_description(
    client: httpx.Client, group_id: str, artifact: str, version: str
) -> str | None:
    text = _maven_pom_text(client, group_id, artifact, version)
    return _maven_description_from_pom_text(text) if text else None


def _npm_contributors_label_from_version_doc(data: dict[str, Any]) -> str | None:
    """Comma-separated maintainer / uploader names (order: maintainers, then ``_npmUser``)."""
    ordered: list[str] = []
    seen_cf: set[str] = set()

    def add(raw: str) -> None:
        s = raw.strip()
        if not s:
            return
        cf = s.casefold()
        if cf not in seen_cf:
            seen_cf.add(cf)
            ordered.append(s)

    mlist = data.get("maintainers")
    if isinstance(mlist, list):
        for m in mlist:
            if isinstance(m, dict):
                n = m.get("name")
                if isinstance(n, str):
                    add(n)
    nu = data.get("_npmUser")
    if isinstance(nu, dict):
        un = nu.get("name")
        if isinstance(un, str):
            add(un)
    return ", ".join(ordered) if ordered else None


def _npm_version_detail(
    client: httpx.Client, package_name: str, version: str
) -> tuple[str | None, str | None]:
    """Return ``(description, contributors_label)`` from the npm version document."""
    enc_pkg = quote(package_name, safe="")
    enc_ver = quote(version, safe="")
    try:
        resp = client.get(f"https://registry.npmjs.org/{enc_pkg}/{enc_ver}")
        if resp.status_code != 200:
            return None, None
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return None, None
        if not isinstance(data, dict):
            return None, None
        d = data.get("description")
        desc = d if isinstance(d, str) else None
        pub = _npm_contributors_label_from_version_doc(data)
        return desc, pub
    except httpx.HTTPError:
        return None, None


def _npm_version_description(
    client: httpx.Client, package_name: str, version: str
) -> str | None:
    desc, _pub = _npm_version_detail(client, package_name, version)
    return desc


def _github_release_publisher(rel: dict[str, Any]) -> str | None:
    author = rel.get("author")
    if not isinstance(author, dict):
        return None
    login = author.get("login")
    if not isinstance(login, str) or not login.strip():
        return None
    name = author.get("name")
    display = name.strip() if isinstance(name, str) and name.strip() else None
    return format_publisher_label(display, login.strip())


@dataclass(slots=True)
class SourceContext:
    start: datetime
    end: datetime
    landscape: LandscapeIndex
    client: httpx.Client
    finos_repo_names: frozenset[str] = field(default_factory=frozenset)
    progress: Callable[[str], None] | None = None


def crawl_github(context: SourceContext) -> list[Release]:
    releases: list[Release] = []
    if context.finos_repo_names:
        repo_names = sorted(context.finos_repo_names)
    else:
        repos = context.client.get(
            "https://api.github.com/orgs/finos/repos?per_page=100",
            headers=github_api_headers(),
        ).json()
        if not isinstance(repos, list):
            return releases
        repo_names = [
            r["name"]
            for r in repos
            if isinstance(r, dict) and isinstance(r.get("name"), str)
        ]

    for name in repo_names:
        project, repo_slug = resolve_project_and_repo(
            context.landscape, context.finos_repo_names, [name]
        )
        github_repo = full_github_name(repo_slug or name)
        rels = context.client.get(
            f"https://api.github.com/repos/finos/{name}/releases?per_page=100",
            headers=github_api_headers(),
        ).json()
        if not isinstance(rels, list):
            continue
        for rel in rels:
            if not isinstance(rel, dict):
                continue
            published = rel.get("published_at")
            tag_name = rel.get("tag_name")
            html_url = rel.get("html_url")
            if not all(isinstance(x, str) for x in (published, tag_name, html_url)):
                continue
            when = _parse_iso_datetime(published)
            if _in_range(when, context.start, context.end):
                body = rel.get("body")
                desc_raw = body if isinstance(body, str) else None
                releases.append(
                    Release(
                        project=project,
                        source="github",
                        artifact=name,
                        version=tag_name,
                        url=html_url,
                        released_at=when,
                        github_repo=github_repo,
                        description=normalize_release_description(desc_raw),
                        publisher=_github_release_publisher(rel),
                    )
                )
    return releases


def _iter_maven_finos_ga_docs(
    client: httpx.Client,
    *,
    progress: Callable[[str], None] | None = None,
    rows: int = 200,
    max_pages: int = 50,
):
    """Yield Solr ``core=ga`` rows: one row per Maven coordinate (groupId + artifactId).

    ``search.maven.org`` ``core=gav`` timestamps lag badly (often months behind Central), so we
    only use Solr to **enumerate** ``org.finos*`` coordinates (~1k rows). Per-version release times
    come from the deps.dev API, which tracks Maven Central ``publishedAt`` accurately.
    """
    start_row = 0
    for _ in range(max_pages):
        resp = client.get(
            "https://search.maven.org/solrsearch/select",
            params={
                "q": "g:org.finos*",
                "start": start_row,
                "rows": rows,
                "wt": "json",
                "core": "ga",
            },
        )
        try:
            data = resp.json()
        except json.JSONDecodeError:
            break
        if not isinstance(data, dict):
            break
        response = data.get("response")
        if not isinstance(response, dict):
            break
        docs = response.get("docs", [])
        num_found = response.get("numFound", 0)
        if not isinstance(docs, list) or not docs:
            break
        yield from docs
        start_row += len(docs)
        if progress and isinstance(num_found, int):
            progress(f"Maven: Central coordinate list {start_row}/{num_found}")
        if isinstance(num_found, int) and start_row >= num_found:
            break


def _maven_deps_dev_headers() -> dict[str, str]:
    return {
        "User-Agent": "weekly-releases (FINOS release crawler; +https://github.com/finos)",
        "Accept": "application/json",
    }


def _maven_versions_from_deps_dev(
    client: httpx.Client, group_id: str, artifact_id: str
) -> list[tuple[str, datetime]]:
    """Return (version, published_at_utc) from deps.dev for a Maven coordinate."""
    enc = quote(f"{group_id}:{artifact_id}", safe="")
    url = f"https://api.deps.dev/v3/systems/maven/packages/{enc}"
    try:
        resp = client.get(url, headers=_maven_deps_dev_headers())
    except httpx.HTTPError:
        return []
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except json.JSONDecodeError:
        return []
    versions = data.get("versions")
    if not isinstance(versions, list):
        return []
    out: list[tuple[str, datetime]] = []
    for entry in versions:
        if not isinstance(entry, dict):
            continue
        vk = entry.get("versionKey")
        published = entry.get("publishedAt")
        if not isinstance(vk, dict) or not isinstance(published, str):
            continue
        ver = vk.get("version")
        if not isinstance(ver, str):
            continue
        try:
            when = _parse_iso_datetime(published)
        except (ValueError, TypeError):
            continue
        out.append((ver, when))
    return out


def _maven_published_at_from_deps_dev_version(
    client: httpx.Client, group_id: str, artifact_id: str, version: str
) -> datetime | None:
    """Return ``publishedAt`` (UTC) for a single Maven version from deps.dev GetVersion."""
    enc_pkg = quote(f"{group_id}:{artifact_id}", safe="")
    enc_ver = quote(version, safe="")
    url = f"https://api.deps.dev/v3/systems/maven/packages/{enc_pkg}/versions/{enc_ver}"
    try:
        resp = client.get(url, headers=_maven_deps_dev_headers())
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    published = data.get("publishedAt")
    if not isinstance(published, str):
        return None
    try:
        return _parse_iso_datetime(published)
    except (ValueError, TypeError):
        return None


def _maven_fetch_solr_gav_timestamp_page(
    client: httpx.Client,
    *,
    start_row: int,
    rows: int,
    lower_ms: int,
    upper_ms: int,
) -> tuple[list[dict[str, Any]], int] | None:
    """One Solr ``core=gav`` page for ``org.finos*`` artifacts in a ``timestamp`` window.

    Returns ``(docs, num_found)`` or ``None`` if the request is unusable (HTTP/JSON/shape).
    """
    q = f"g:org.finos* AND timestamp:[{lower_ms} TO {upper_ms}]"
    try:
        resp = client.get(
            "https://search.maven.org/solrsearch/select",
            params={
                "q": q,
                "start": start_row,
                "rows": rows,
                "wt": "json",
                "core": "gav",
            },
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    response = data.get("response")
    if not isinstance(response, dict):
        return None
    docs = response.get("docs", [])
    num_found = response.get("numFound", 0)
    if not isinstance(docs, list) or not isinstance(num_found, int):
        return None
    clean_docs: list[dict[str, Any]] = [d for d in docs if isinstance(d, dict)]
    return clean_docs, num_found


def _maven_collect_gav_triples_from_solr(
    client: httpx.Client,
    lower_ms: int,
    upper_ms: int,
    *,
    progress: Callable[[str], None] | None = None,
    rows: int = 200,
) -> list[tuple[str, str, str]] | None:
    """Collect unique ``(groupId, artifactId, version)`` from Solr GAV timestamp discovery.

    Returns ``None`` if Solr cannot be read (caller should fall back to the legacy crawl).
    """
    start_row = 0
    num_found: int | None = None
    seen: dict[tuple[str, str, str], None] = {}
    while True:
        page = _maven_fetch_solr_gav_timestamp_page(
            client, start_row=start_row, rows=rows, lower_ms=lower_ms, upper_ms=upper_ms
        )
        if page is None:
            return None
        docs, nf = page
        if num_found is None:
            num_found = nf
            if num_found > MAVEN_SOLR_GAV_MAX_RAW_HITS:
                if progress:
                    progress(
                        "Maven: Solr GAV hit count exceeds cap "
                        f"({num_found} > {MAVEN_SOLR_GAV_MAX_RAW_HITS}); "
                        "falling back to full coordinate scan"
                    )
                return None
        for doc in docs:
            g = doc.get("g")
            a = doc.get("a")
            v = doc.get("v")
            if (
                not isinstance(g, str)
                or not isinstance(a, str)
                or not isinstance(v, str)
            ):
                continue
            key = (g, a, v)
            if key not in seen:
                seen[key] = None
        start_row += len(docs)
        if progress and num_found is not None:
            progress(f"Maven: Solr GAV timestamp window {start_row}/{num_found}")
        if not docs or (num_found is not None and start_row >= num_found):
            break
    return list(seen.keys())


def _maven_releases_for_ga_row(
    context: SourceContext, ga_doc: dict[str, Any]
) -> list[Release]:
    group_id = ga_doc.get("g")
    artifact_id = ga_doc.get("a")
    if not isinstance(group_id, str) or not isinstance(artifact_id, str):
        return []
    keys = [artifact_id, f"{group_id}:{artifact_id}", group_id]
    project, slug = resolve_project_and_repo(
        context.landscape,
        context.finos_repo_names,
        keys,
        maven_group_id=group_id,
    )
    releases: list[Release] = []
    for version, when in _maven_versions_from_deps_dev(
        context.client, group_id, artifact_id
    ):
        if not _in_range(when, context.start, context.end):
            continue
        pom_text = _maven_pom_text(context.client, group_id, artifact_id, version)
        if pom_text:
            pom_desc = _maven_description_from_pom_text(pom_text)
            publisher = _maven_contributors_label(
                context.client,
                group_id,
                artifact_id,
                version,
                leaf_pom_text=pom_text,
            )
        else:
            pom_desc = None
            publisher = None
        releases.append(
            Release(
                project=project,
                source="maven",
                artifact=f"{group_id}:{artifact_id}",
                version=version,
                url=_maven_search_artifact_url(group_id, artifact_id, version),
                released_at=when,
                github_repo=full_github_name(slug),
                description=normalize_release_description(pom_desc),
                publisher=publisher,
            )
        )
    return releases


def _maven_releases_for_gav_triple(
    context: SourceContext, group_id: str, artifact_id: str, version: str
) -> list[Release]:
    """Build zero or one ``Release`` for a ``(groupId, artifactId, version)`` using deps.dev GetVersion."""
    when = _maven_published_at_from_deps_dev_version(
        context.client, group_id, artifact_id, version
    )
    if when is None or not _in_range(when, context.start, context.end):
        return []
    keys = [artifact_id, f"{group_id}:{artifact_id}", group_id]
    project, slug = resolve_project_and_repo(
        context.landscape,
        context.finos_repo_names,
        keys,
        maven_group_id=group_id,
    )
    pom_text = _maven_pom_text(context.client, group_id, artifact_id, version)
    if pom_text:
        pom_desc = _maven_description_from_pom_text(pom_text)
        publisher = _maven_contributors_label(
            context.client,
            group_id,
            artifact_id,
            version,
            leaf_pom_text=pom_text,
        )
    else:
        pom_desc = None
        publisher = None
    return [
        Release(
            project=project,
            source="maven",
            artifact=f"{group_id}:{artifact_id}",
            version=version,
            url=_maven_search_artifact_url(group_id, artifact_id, version),
            released_at=when,
            github_repo=full_github_name(slug),
            description=normalize_release_description(pom_desc),
            publisher=publisher,
        )
    ]


def _crawl_maven_legacy_full_scan(context: SourceContext) -> list[Release]:
    """Enumerate every ``org.finos*`` GA coordinate and scan all versions via deps.dev GetPackage."""
    prog = context.progress
    packages = [
        d
        for d in _iter_maven_finos_ga_docs(context.client, progress=prog)
        if isinstance(d, dict)
    ]
    if not packages:
        return []
    total = len(packages)
    workers = min(12, max(1, total))
    if prog:
        prog(
            f"Maven: querying deps.dev + POMs for {total} coordinates "
            f"({workers} parallel workers)"
        )
    releases: list[Release] = []
    progress_interval = max(1, min(80, total // 12))
    completed = 0
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_maven_releases_for_ga_row, context, doc) for doc in packages
        ]
        for fut in as_completed(futures):
            batch = fut.result()
            with lock:
                releases.extend(batch)
                completed += 1
                n_rel = len(releases)
                if prog and (
                    completed == 1
                    or completed == total
                    or completed % progress_interval == 0
                ):
                    pct = 100 * completed // total
                    prog(
                        f"Maven: coordinates {completed}/{total} ({pct}%), "
                        f"{n_rel} release(s) in crawl window so far"
                    )
    releases.sort(key=lambda r: r.released_at)
    return releases


def crawl_maven(context: SourceContext) -> list[Release]:
    prog = context.progress
    lower_ms, upper_ms = maven_solr_gav_timestamp_bounds(context.start, context.end)
    if prog:
        prog(
            "Maven: Solr GAV timestamp discovery "
            f"(buffer {MAVEN_SOLR_DISCOVERY_BUFFER_DAYS}d before crawl start)"
        )
    triples = _maven_collect_gav_triples_from_solr(
        context.client,
        lower_ms,
        upper_ms,
        progress=prog,
    )
    if triples is None:
        if prog:
            prog(
                "Maven: Solr GAV discovery failed or exceeded cap; full coordinate scan"
            )
        return _crawl_maven_legacy_full_scan(context)
    if not triples:
        # Solr ``core=gav`` timestamps often lag badly; a successful query with zero docs is
        # common for recent crawl windows even when Central has fresh artifacts. Enumerate GA.
        if prog:
            prog(
                "Maven: Solr GAV timestamp window returned no hits; "
                "full coordinate scan (core=ga + deps.dev)"
            )
        return _crawl_maven_legacy_full_scan(context)
    total = len(triples)
    workers = min(12, max(1, total))
    if prog:
        prog(
            f"Maven: deps.dev GetVersion + POMs for {total} unique releases "
            f"({workers} parallel workers)"
        )
    releases: list[Release] = []
    progress_interval = max(1, min(80, total // 12))
    completed = 0
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_maven_releases_for_gav_triple, context, g, a, v)
            for g, a, v in triples
        ]
        for fut in as_completed(futures):
            batch = fut.result()
            with lock:
                releases.extend(batch)
                completed += 1
                n_rel = len(releases)
                if prog and (
                    completed == 1
                    or completed == total
                    or completed % progress_interval == 0
                ):
                    pct = 100 * completed // total
                    prog(
                        f"Maven: GAV keys {completed}/{total} ({pct}%), "
                        f"{n_rel} release(s) in crawl window so far"
                    )
    releases.sort(key=lambda r: r.released_at)
    return releases


def _npm_search_payload(resp: httpx.Response) -> dict[str, Any]:
    """Parse npm ``/-/v1/search`` JSON or raise with enough detail to debug proxies/HTML bodies."""
    if resp.status_code >= 400:
        preview = (resp.text or "")[:400].replace("\n", " ")
        raise RuntimeError(
            f"npm registry search failed: HTTP {resp.status_code} (body starts: {preview!r})"
        )
    try:
        payload = resp.json()
    except json.JSONDecodeError as exc:
        preview = (resp.text or "")[:400].replace("\n", " ")
        ct = resp.headers.get("content-type", "")
        raise RuntimeError(
            f"npm registry search returned non-JSON (HTTP {resp.status_code}, "
            f"content-type={ct!r}, body starts: {preview!r})"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"npm registry search returned unexpected JSON type {type(payload).__name__!r}"
        )
    return payload


def crawl_npm(context: SourceContext) -> list[Release]:
    """Discover ``@finos/*`` packages via registry search.

    The npm v1 search endpoint returns **no hits** for ``scope:finos``; ``text=@finos`` matches
    scoped packages in practice.
    """
    releases: list[Release] = []
    page_size = 250
    offset = 0
    while True:
        resp = context.client.get(
            "https://registry.npmjs.org/-/v1/search",
            params={"text": "@finos", "size": page_size, "from": offset},
        )
        data = _npm_search_payload(resp)
        objects = data.get("objects", [])
        total = data.get("total")
        if not isinstance(objects, list) or not objects:
            break
        for obj in objects:
            pkg = obj.get("package", {})
            name = pkg.get("name")
            version = pkg.get("version")
            date = pkg.get("date")
            links = pkg.get("links", {})
            url = links.get("npm")
            if not all(isinstance(x, str) for x in (name, version, date, url)):
                continue
            when = _parse_iso_datetime(date)
            if not _in_range(when, context.start, context.end):
                continue
            keys = [name]
            if isinstance(name, str) and name.startswith("@finos/"):
                keys.append(name.split("/", 1)[1])
            project, slug = resolve_project_and_repo(
                context.landscape, context.finos_repo_names, keys
            )
            npm_desc, npm_pub = _npm_version_detail(context.client, name, version)
            releases.append(
                Release(
                    project=project,
                    source="npm",
                    artifact=name,
                    version=version,
                    url=url,
                    released_at=when,
                    github_repo=full_github_name(slug),
                    description=normalize_release_description(npm_desc),
                    publisher=npm_pub,
                )
            )
        offset += len(objects)
        if isinstance(total, (int, float)):
            if offset >= int(total):
                break
        elif len(objects) < page_size:
            break
    return releases


def _pypi_contributors_from_info(info: dict[str, Any]) -> str | None:
    """Comma-separated names from ``info.author`` / ``info.maintainer`` (split on commas)."""
    ordered: list[str] = []
    seen_cf: set[str] = set()
    for key in ("author", "maintainer"):
        raw = info.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        for piece in raw.split(","):
            s = piece.strip()
            if not s:
                continue
            cf = s.casefold()
            if cf not in seen_cf:
                seen_cf.add(cf)
                ordered.append(s)
    return ", ".join(ordered) if ordered else None


def crawl_pypi(context: SourceContext) -> list[Release]:
    user_page = context.client.get("https://pypi.org/user/finos/").text
    finos_candidates = sorted(set(re.findall(r"/project/([^/]+)/", user_page)))
    releases: list[Release] = []
    for package in finos_candidates:
        meta = context.client.get(f"https://pypi.org/pypi/{package}/json")
        if meta.status_code != 200:
            continue
        try:
            payload = meta.json()
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        info_raw = payload.get("info", {})
        info = info_raw if isinstance(info_raw, dict) else {}
        version = info.get("version")
        if not isinstance(version, str):
            continue
        releases_raw = payload.get("releases", {})
        if not isinstance(releases_raw, dict):
            continue
        files_raw = releases_raw.get(version, [])
        files = files_raw if isinstance(files_raw, list) else []
        if not files:
            continue
        upload_time = files[-1].get("upload_time_iso_8601")
        url = files[-1].get("url")
        if not isinstance(upload_time, str) or not isinstance(url, str):
            continue
        when = _parse_iso_datetime(upload_time)
        if not _in_range(when, context.start, context.end):
            continue
        project, slug = resolve_project_and_repo(
            context.landscape, context.finos_repo_names, [package]
        )
        summary = info.get("summary")
        long_desc = info.get("description")
        if isinstance(summary, str) and summary.strip():
            py_raw: str | None = summary
        elif isinstance(long_desc, str) and long_desc.strip():
            py_raw = long_desc
        else:
            py_raw = None
        py_pub = _pypi_contributors_from_info(info)
        releases.append(
            Release(
                project=project,
                source="pypi",
                artifact=package,
                version=version,
                url=url,
                released_at=when,
                github_repo=full_github_name(slug),
                description=normalize_release_description(py_raw),
                publisher=py_pub,
            )
        )
    return releases


def crawl_docker_hub(context: SourceContext) -> list[Release]:
    repos = context.client.get(
        "https://hub.docker.com/v2/repositories/finos/?page_size=100"
    ).json()
    if not isinstance(repos, dict):
        return []
    releases: list[Release] = []
    for entry in repos.get("results", []):
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        repo_resp = context.client.get(
            f"https://hub.docker.com/v2/repositories/finos/{name}/"
        )
        repo_detail = repo_resp.json() if repo_resp.status_code == 200 else {}
        docker_raw = None
        if isinstance(repo_detail, dict):
            fd = repo_detail.get("full_description")
            sd = repo_detail.get("description")
            docker_raw = (fd if isinstance(fd, str) and fd.strip() else None) or (
                sd if isinstance(sd, str) and sd.strip() else None
            )
        docker_desc = normalize_release_description(docker_raw)

        tags = context.client.get(
            f"https://hub.docker.com/v2/repositories/finos/{name}/tags?page_size=50"
        ).json()
        if not isinstance(tags, dict):
            continue
        for tag in tags.get("results", []):
            tag_name = tag.get("name")
            updated = tag.get("last_updated")
            if not isinstance(tag_name, str) or not isinstance(updated, str):
                continue
            when = _parse_iso_datetime(updated)
            if not _in_range(when, context.start, context.end):
                continue
            keys = [f"finos/{name}", name]
            project, slug = resolve_project_and_repo(
                context.landscape, context.finos_repo_names, keys
            )
            lu = tag.get("last_updater_username")
            docker_pub = (
                format_publisher_label(None, lu.strip())
                if isinstance(lu, str) and lu.strip()
                else None
            )
            releases.append(
                Release(
                    project=project,
                    source="docker",
                    artifact=f"finos/{name}",
                    version=tag_name,
                    url=f"https://hub.docker.com/r/finos/{name}/tags",
                    released_at=when,
                    github_repo=full_github_name(slug),
                    description=docker_desc,
                    publisher=docker_pub,
                )
            )
    return releases
