from datetime import datetime, timezone

import pytest

from weekly_releases.landscape import LandscapeIndex
from weekly_releases.sources import (
    SourceContext,
    crawl_docker_hub,
    crawl_github,
    crawl_maven,
    crawl_npm,
    crawl_pypi,
)


class FakeResponse:
    def __init__(self, *, json_data=None, text_data="", status_code=200, headers=None):
        self._json_data = json_data
        self.text = text_data
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        import json

        if self._json_data is not None:
            return self._json_data
        return json.loads(self.text)


class FakeClient:
    def __init__(self, data):
        self.data = data

    def get(self, url, params=None, headers=None):
        key = (url, tuple(sorted((params or {}).items())))
        if key in self.data:
            return self.data[key]
        return self.data[url]


def build_context(fake_data, *, finos_repo_names: frozenset[str] | None = None):
    idx = LandscapeIndex(repo_to_project={"repo": "Project"}, asset_to_project={"artifact": "Project"})
    repos = finos_repo_names if finos_repo_names is not None else frozenset({"repo", "artifact"})
    return SourceContext(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 10, tzinfo=timezone.utc),
        landscape=idx,
        client=FakeClient(fake_data),
        finos_repo_names=repos,
    )


def test_crawl_github_filters_dates():
    context = build_context(
        {
            "https://api.github.com/orgs/finos/repos?per_page=100": FakeResponse(
                json_data=[{"name": "repo"}]
            ),
            "https://api.github.com/repos/finos/repo/releases?per_page=100": FakeResponse(
                json_data=[
                    {
                        "published_at": "2026-01-02T00:00:00Z",
                        "tag_name": "v1",
                        "html_url": "https://gh/r",
                        "body": "Bug fixes and docs.",
                    },
                    {
                        "published_at": "2025-12-02T00:00:00Z",
                        "tag_name": "old",
                        "html_url": "https://gh/old",
                    },
                ]
            ),
        },
        finos_repo_names=frozenset({"repo"}),
    )
    out = crawl_github(context)
    assert len(out) == 1
    assert out[0].project == "Project"
    assert out[0].description == "Bug fixes and docs."


def test_crawl_github_handles_unexpected_payload_shape():
    context = build_context(
        {
            "https://api.github.com/orgs/finos/repos?per_page=100": FakeResponse(
                json_data=[{"name": "repo"}]
            ),
            "https://api.github.com/repos/finos/repo/releases?per_page=100": FakeResponse(
                json_data={"message": "API rate limit exceeded"}
            ),
        },
        finos_repo_names=frozenset({"repo"}),
    )
    out = crawl_github(context)
    assert out == []


def test_crawl_maven_and_npm_and_docker():
    fake = {
        (
            "https://search.maven.org/solrsearch/select",
            (("core", "ga"), ("q", "g:org.finos*"), ("rows", 200), ("start", 0), ("wt", "json")),
        ): FakeResponse(
            json_data={
                "response": {
                    "numFound": 1,
                    "docs": [{"g": "org.finos", "a": "artifact", "latestVersion": "1.2.3"}],
                }
            }
        ),
        "https://api.deps.dev/v3/systems/maven/packages/org.finos%3Aartifact": FakeResponse(
            json_data={
                "versions": [
                    {
                        "versionKey": {
                            "system": "MAVEN",
                            "name": "org.finos:artifact",
                            "version": "1.2.3",
                        },
                        "publishedAt": "2026-01-05T12:00:00Z",
                    }
                ]
            }
        ),
        (
            "https://registry.npmjs.org/-/v1/search",
            (("from", 0), ("size", 250), ("text", "@finos")),
        ): FakeResponse(
            json_data={
                "total": 1,
                "objects": [
                    {
                        "package": {
                            "name": "@finos/artifact",
                            "version": "2.0.0",
                            "date": "2026-01-03T00:00:00Z",
                            "links": {"npm": "https://npm/artifact"},
                        }
                    }
                ],
            }
        ),
        "https://repo1.maven.org/maven2/org/finos/artifact/1.2.3/artifact-1.2.3.pom": FakeResponse(
            text_data="<project><description>Maven coordinate</description></project>"
        ),
        "https://registry.npmjs.org/%40finos%2Fartifact/2.0.0": FakeResponse(
            json_data={"description": "Scoped npm artifact"}
        ),
        "https://hub.docker.com/v2/repositories/finos/?page_size=100": FakeResponse(
            json_data={"results": [{"name": "artifact"}]}
        ),
        "https://hub.docker.com/v2/repositories/finos/artifact/": FakeResponse(
            json_data={"description": "Container image"}
        ),
        "https://hub.docker.com/v2/repositories/finos/artifact/tags?page_size=50": FakeResponse(
            json_data={"results": [{"name": "latest", "last_updated": "2026-01-04T00:00:00Z"}]}
        ),
    }
    context = build_context(fake)
    mvn_rels = crawl_maven(context)
    assert len(mvn_rels) == 1
    assert mvn_rels[0].artifact == "org.finos:artifact"
    assert mvn_rels[0].description == "Maven coordinate"
    npm_rels = crawl_npm(context)
    assert len(npm_rels) == 1
    assert npm_rels[0].description == "Scoped npm artifact"
    dock = crawl_docker_hub(context)
    assert len(dock) == 1
    assert dock[0].description == "Container image"


def test_crawl_maven_nested_group_id_pom_path():
    fake = {
        (
            "https://search.maven.org/solrsearch/select",
            (("core", "ga"), ("q", "g:org.finos*"), ("rows", 200), ("start", 0), ("wt", "json")),
        ): FakeResponse(
            json_data={
                "response": {
                    "numFound": 1,
                    "docs": [{"g": "org.finos.demo", "a": "lib", "latestVersion": "1.0.0"}],
                }
            }
        ),
        "https://api.deps.dev/v3/systems/maven/packages/org.finos.demo%3Alib": FakeResponse(
            json_data={
                "versions": [
                    {
                        "versionKey": {
                            "system": "MAVEN",
                            "name": "org.finos.demo:lib",
                            "version": "1.0.0",
                        },
                        "publishedAt": "2026-01-05T12:00:00Z",
                    }
                ]
            }
        ),
        "https://repo1.maven.org/maven2/org/finos/demo/lib/1.0.0/lib-1.0.0.pom": FakeResponse(
            text_data="<project><description>nested</description></project>"
        ),
    }
    context = build_context(fake)
    mvn = crawl_maven(context)
    assert len(mvn) == 1
    assert mvn[0].artifact == "org.finos.demo:lib"
    assert mvn[0].description == "nested"


def test_crawl_npm_search_empty_body_raises_clear_error():
    fake = {
        (
            "https://registry.npmjs.org/-/v1/search",
            (("from", 0), ("size", 250), ("text", "@finos")),
        ): FakeResponse(text_data="", status_code=200),
    }
    context = build_context(fake)
    with pytest.raises(RuntimeError, match="npm registry search returned non-JSON"):
        crawl_npm(context)


def test_crawl_npm_search_http_error_raises_clear_error():
    fake = {
        (
            "https://registry.npmjs.org/-/v1/search",
            (("from", 0), ("size", 250), ("text", "@finos")),
        ): FakeResponse(text_data="<html>bad gateway</html>", status_code=502),
    }
    context = build_context(fake)
    with pytest.raises(RuntimeError, match=r"npm registry search failed: HTTP 502"):
        crawl_npm(context)


def test_crawl_pypi():
    fake = {
        "https://pypi.org/user/finos/": FakeResponse(
            text_data='<a href="/project/artifact/">artifact</a>'
        ),
        "https://pypi.org/pypi/artifact/json": FakeResponse(
            json_data={
                "info": {"version": "1.0.0", "summary": "Sample Python wheel"},
                "releases": {
                    "1.0.0": [
                        {
                            "upload_time_iso_8601": "2026-01-04T00:00:00Z",
                            "url": "https://pypi/artifact",
                        }
                    ]
                },
            }
        ),
    }
    context = build_context(fake)
    py = crawl_pypi(context)
    assert len(py) == 1
    assert py[0].description == "Sample Python wheel"


def test_crawl_pypi_skips_missing_package():
    fake = {
        "https://pypi.org/user/finos/": FakeResponse(text_data='<a href="/project/missing/">x</a>'),
        "https://pypi.org/pypi/missing/json": FakeResponse(status_code=404, json_data={}),
    }
    context = build_context(fake)
    assert crawl_pypi(context) == []

