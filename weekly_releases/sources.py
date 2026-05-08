from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
from typing import Any
from urllib.parse import quote

import httpx

from weekly_releases.github_auth import github_api_headers
from weekly_releases.description_text import normalize_release_description
from weekly_releases.landscape import LandscapeIndex
from weekly_releases.models import Release
from weekly_releases.resolution import full_github_name, resolve_project_and_repo


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _in_range(ts: datetime, start: datetime, end: datetime) -> bool:
    return start <= ts <= end


def _maven_pom_url(group_id: str, artifact: str, version: str) -> str:
    """Central Repository path: group dots become directories."""
    rel = "/".join(group_id.split(".")) + f"/{quote(artifact, safe='.-_')}/{quote(version, safe='.-_')}/{artifact}-{version}.pom"
    return f"https://repo1.maven.org/maven2/{rel}"


def _maven_search_artifact_url(group_id: str, artifact: str, version: str) -> str:
    g = quote(group_id, safe=".")
    a = quote(artifact, safe=".")
    v = quote(version, safe=".")
    return f"https://search.maven.org/artifact/{g}/{a}/{v}/jar"


def _maven_pom_description(client: httpx.Client, group_id: str, artifact: str, version: str) -> str | None:
    url = _maven_pom_url(group_id, artifact, version)
    try:
        resp = client.get(url)
        if resp.status_code != 200:
            return None
        m = re.search(r"<description>\s*(.*?)\s*</description>", resp.text, re.DOTALL)
        if not m:
            return None
        inner = m.group(1).strip()
        if inner.startswith("<![CDATA[") and inner.endswith("]]>"):
            inner = inner[9:-3].strip()
        return inner or None
    except httpx.HTTPError:
        return None


def _npm_version_description(client: httpx.Client, package_name: str, version: str) -> str | None:
    enc_pkg = quote(package_name, safe="")
    enc_ver = quote(version, safe="")
    try:
        resp = client.get(f"https://registry.npmjs.org/{enc_pkg}/{enc_ver}")
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        d = data.get("description")
        return d if isinstance(d, str) else None
    except httpx.HTTPError:
        return None


@dataclass(slots=True)
class SourceContext:
    start: datetime
    end: datetime
    landscape: LandscapeIndex
    client: httpx.Client
    finos_repo_names: frozenset[str] = field(default_factory=frozenset)


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
                    )
                )
    return releases


def _iter_maven_finos_ga_docs(client: httpx.Client, *, rows: int = 200, max_pages: int = 50):
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
        if isinstance(num_found, int) and start_row >= num_found:
            break


def _maven_versions_from_deps_dev(
    client: httpx.Client, group_id: str, artifact_id: str
) -> list[tuple[str, datetime]]:
    """Return (version, published_at_utc) from deps.dev for a Maven coordinate."""
    enc = quote(f"{group_id}:{artifact_id}", safe="")
    url = f"https://api.deps.dev/v3/systems/maven/packages/{enc}"
    headers = {
        "User-Agent": "weekly-releases (FINOS release crawler; +https://github.com/finos)",
        "Accept": "application/json",
    }
    try:
        resp = client.get(url, headers=headers)
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


def _maven_releases_for_ga_row(context: SourceContext, ga_doc: dict[str, Any]) -> list[Release]:
    group_id = ga_doc.get("g")
    artifact_id = ga_doc.get("a")
    if not isinstance(group_id, str) or not isinstance(artifact_id, str):
        return []
    keys = [artifact_id, f"{group_id}:{artifact_id}", group_id]
    project, slug = resolve_project_and_repo(
        context.landscape, context.finos_repo_names, keys
    )
    releases: list[Release] = []
    for version, when in _maven_versions_from_deps_dev(context.client, group_id, artifact_id):
        if not _in_range(when, context.start, context.end):
            continue
        pom_desc = _maven_pom_description(context.client, group_id, artifact_id, version)
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
            )
        )
    return releases


def crawl_maven(context: SourceContext) -> list[Release]:
    packages = [d for d in _iter_maven_finos_ga_docs(context.client) if isinstance(d, dict)]
    if not packages:
        return []
    workers = min(12, max(1, len(packages)))
    releases: list[Release] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_maven_releases_for_ga_row, context, doc) for doc in packages]
        for fut in as_completed(futures):
            releases.extend(fut.result())
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
            npm_desc = _npm_version_description(context.client, name, version)
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
                )
            )
        offset += len(objects)
        if isinstance(total, (int, float)):
            if offset >= int(total):
                break
        elif len(objects) < page_size:
            break
    return releases


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
            )
        )
    return releases


def crawl_docker_hub(context: SourceContext) -> list[Release]:
    repos = context.client.get("https://hub.docker.com/v2/repositories/finos/?page_size=100").json()
    if not isinstance(repos, dict):
        return []
    releases: list[Release] = []
    for entry in repos.get("results", []):
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        repo_resp = context.client.get(f"https://hub.docker.com/v2/repositories/finos/{name}/")
        repo_detail = repo_resp.json() if repo_resp.status_code == 200 else {}
        docker_raw = None
        if isinstance(repo_detail, dict):
            fd = repo_detail.get("full_description")
            sd = repo_detail.get("description")
            docker_raw = (
                fd if isinstance(fd, str) and fd.strip() else None
            ) or (sd if isinstance(sd, str) and sd.strip() else None)
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
                )
            )
    return releases

