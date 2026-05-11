import xmlrpc.client
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
import pytest
from weekly_releases.landscape import LandscapeIndex
from weekly_releases.sources import (
    SourceContext,
    _maven_contributors_label,
    _maven_developer_labels_from_pom_text,
    _maven_pom_description,
    _maven_pom_url,
    _npm_version_description,
    crawl_docker_hub,
    crawl_github,
    crawl_maven,
    crawl_npm,
    crawl_pypi,
    maven_solr_gav_timestamp_bounds,
)

_CTX_START = datetime(2026, 1, 1, tzinfo=UTC)
_CTX_END = datetime(2026, 1, 10, tzinfo=UTC)


def _solr_gav_select_key(*, start_row: int = 0, rows: int = 200) -> tuple:
    lo, hi = maven_solr_gav_timestamp_bounds(_CTX_START, _CTX_END)
    q = f"g:org.finos* AND timestamp:[{lo} TO {hi}]"
    return (
        "https://search.maven.org/solrsearch/select",
        tuple(
            sorted(
                (
                    ("core", "gav"),
                    ("q", q),
                    ("rows", rows),
                    ("start", start_row),
                    ("wt", "json"),
                )
            )
        ),
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

    def post(self, url, *, content=None, headers=None):
        # Tests can register a per-URL response (most cases) or a tuple
        # ``(url, content)`` key when they need to assert on the body.
        body_key = (url, content)
        if body_key in self.data:
            return self.data[body_key]
        return self.data[url]


def build_context(fake_data, *, finos_repo_names: frozenset[str] | None = None):
    idx = LandscapeIndex(
        repo_to_project={"repo": "Project"}, asset_to_project={"artifact": "Project"}
    )
    repos = (
        finos_repo_names
        if finos_repo_names is not None
        else frozenset({"repo", "artifact"})
    )
    return SourceContext(
        start=_CTX_START,
        end=_CTX_END,
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
                        "author": {
                            "login": "octocat",
                            "name": "Monalisa Octocat",
                        },
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
    assert out[0].publisher == "Monalisa Octocat (octocat)"


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
        _solr_gav_select_key(): FakeResponse(
            json_data={
                "response": {
                    "numFound": 1,
                    "docs": [
                        {
                            "g": "org.finos",
                            "a": "artifact",
                            "v": "1.2.3",
                            "p": "jar",
                            "timestamp": 1736072400000,
                        }
                    ],
                }
            }
        ),
        "https://api.deps.dev/v3/systems/maven/packages/org.finos%3Aartifact/versions/1.2.3": FakeResponse(
            json_data={
                "versionKey": {
                    "system": "MAVEN",
                    "name": "org.finos:artifact",
                    "version": "1.2.3",
                },
                "publishedAt": "2026-01-05T12:00:00Z",
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
            text_data=(
                "<project><description>Maven coordinate</description>"
                "<developers><developer><name>Jane Doe</name><id>jdoe</id></developer>"
                "</developers></project>"
            )
        ),
        "https://registry.npmjs.org/%40finos%2Fartifact/2.0.0": FakeResponse(
            json_data={
                "description": "Scoped npm artifact",
                "maintainers": [{"name": "alice"}, {"name": "bob"}],
                "_npmUser": {"name": "npm-user"},
            }
        ),
        "https://hub.docker.com/v2/repositories/finos/?page_size=100": FakeResponse(
            json_data={"results": [{"name": "artifact"}]}
        ),
        "https://hub.docker.com/v2/repositories/finos/artifact/": FakeResponse(
            json_data={"description": "Container image"}
        ),
        "https://hub.docker.com/v2/repositories/finos/artifact/tags?page_size=50": FakeResponse(
            json_data={
                "results": [
                    {
                        "name": "latest",
                        "last_updated": "2026-01-04T00:00:00Z",
                        "last_updater_username": "finos",
                    }
                ]
            }
        ),
    }
    context = build_context(fake)
    mvn_rels = crawl_maven(context)
    assert len(mvn_rels) == 1
    assert mvn_rels[0].artifact == "org.finos:artifact"
    assert mvn_rels[0].description == "Maven coordinate"
    assert mvn_rels[0].publisher == "Jane Doe (jdoe)"
    npm_rels = crawl_npm(context)
    assert len(npm_rels) == 1
    assert npm_rels[0].description == "Scoped npm artifact"
    assert npm_rels[0].publisher == "alice, bob, npm-user"
    dock = crawl_docker_hub(context)
    assert len(dock) == 1
    assert dock[0].description == "Container image"
    assert dock[0].publisher == "finos"


def test_crawl_maven_nested_group_id_pom_path():
    fake = {
        _solr_gav_select_key(): FakeResponse(
            json_data={
                "response": {
                    "numFound": 1,
                    "docs": [
                        {
                            "g": "org.finos.demo",
                            "a": "lib",
                            "v": "1.0.0",
                            "p": "jar",
                            "timestamp": 1736072400000,
                        }
                    ],
                }
            }
        ),
        "https://api.deps.dev/v3/systems/maven/packages/org.finos.demo%3Alib/versions/1.0.0": FakeResponse(
            json_data={
                "versionKey": {
                    "system": "MAVEN",
                    "name": "org.finos.demo:lib",
                    "version": "1.0.0",
                },
                "publishedAt": "2026-01-05T12:00:00Z",
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


def test_maven_solr_gav_timestamp_bounds_includes_buffer():
    lo, hi = maven_solr_gav_timestamp_bounds(_CTX_START, _CTX_END)
    assert hi == int(_CTX_END.timestamp() * 1000)
    assert lo < int(_CTX_START.timestamp() * 1000)


def test_crawl_maven_solr_empty_falls_back_to_legacy_scan():
    """Solr GAV succeeds but returns zero docs → enumerate GA (timestamps often lag)."""
    fake = {
        _solr_gav_select_key(): FakeResponse(
            json_data={"response": {"numFound": 0, "docs": []}},
        ),
        (
            "https://search.maven.org/solrsearch/select",
            (
                ("core", "ga"),
                ("q", "g:org.finos*"),
                ("rows", 200),
                ("start", 0),
                ("wt", "json"),
            ),
        ): FakeResponse(
            json_data={
                "response": {
                    "numFound": 1,
                    "docs": [
                        {"g": "org.finos", "a": "emptySolr", "latestVersion": "1.0.0"}
                    ],
                }
            }
        ),
        "https://api.deps.dev/v3/systems/maven/packages/org.finos%3AemptySolr": FakeResponse(
            json_data={
                "versions": [
                    {
                        "versionKey": {
                            "system": "MAVEN",
                            "name": "org.finos:emptySolr",
                            "version": "1.0.0",
                        },
                        "publishedAt": "2026-01-05T12:00:00Z",
                    }
                ]
            }
        ),
        "https://repo1.maven.org/maven2/org/finos/emptySolr/1.0.0/emptySolr-1.0.0.pom": FakeResponse(
            text_data="<project><description>via legacy after empty GAV</description></project>"
        ),
    }
    context = build_context(fake)
    rels = crawl_maven(context)
    assert len(rels) == 1
    assert rels[0].artifact == "org.finos:emptySolr"
    assert rels[0].description == "via legacy after empty GAV"


def test_crawl_maven_solr_dedupes_identical_gav_triples():
    fake = {
        _solr_gav_select_key(): FakeResponse(
            json_data={
                "response": {
                    "numFound": 2,
                    "docs": [
                        {
                            "g": "org.finos",
                            "a": "dup",
                            "v": "1.0.0",
                            "p": "jar",
                            "timestamp": 1,
                        },
                        {
                            "g": "org.finos",
                            "a": "dup",
                            "v": "1.0.0",
                            "p": "pom",
                            "timestamp": 2,
                        },
                    ],
                }
            }
        ),
        "https://api.deps.dev/v3/systems/maven/packages/org.finos%3Adup/versions/1.0.0": FakeResponse(
            json_data={
                "versionKey": {
                    "system": "MAVEN",
                    "name": "org.finos:dup",
                    "version": "1.0.0",
                },
                "publishedAt": "2026-01-05T12:00:00Z",
            }
        ),
        "https://repo1.maven.org/maven2/org/finos/dup/1.0.0/dup-1.0.0.pom": FakeResponse(
            text_data="<project><description>dup one</description></project>"
        ),
    }
    context = build_context(fake)
    rels = crawl_maven(context)
    assert len(rels) == 1
    assert rels[0].version == "1.0.0"


def test_crawl_maven_filters_using_deps_getversion_not_solr_row_time():
    """Solr supplies candidates; authoritative ``publishedAt`` comes from deps.dev."""
    fake = {
        _solr_gav_select_key(): FakeResponse(
            json_data={
                "response": {
                    "numFound": 1,
                    "docs": [
                        {
                            "g": "org.finos",
                            "a": "late",
                            "v": "2.0.0",
                            "p": "jar",
                            "timestamp": 1,
                        }
                    ],
                }
            }
        ),
        "https://api.deps.dev/v3/systems/maven/packages/org.finos%3Alate/versions/2.0.0": FakeResponse(
            json_data={
                "versionKey": {
                    "system": "MAVEN",
                    "name": "org.finos:late",
                    "version": "2.0.0",
                },
                "publishedAt": "2026-02-01T12:00:00Z",
            }
        ),
    }
    context = build_context(fake)
    assert crawl_maven(context) == []


def test_crawl_maven_solr_http_error_falls_back_to_legacy_scan():
    fake = {
        _solr_gav_select_key(): FakeResponse(status_code=503, json_data={}),
        (
            "https://search.maven.org/solrsearch/select",
            (
                ("core", "ga"),
                ("q", "g:org.finos*"),
                ("rows", 200),
                ("start", 0),
                ("wt", "json"),
            ),
        ): FakeResponse(
            json_data={
                "response": {
                    "numFound": 1,
                    "docs": [{"g": "org.finos", "a": "leg", "latestVersion": "0.1.0"}],
                }
            }
        ),
        "https://api.deps.dev/v3/systems/maven/packages/org.finos%3Aleg": FakeResponse(
            json_data={
                "versions": [
                    {
                        "versionKey": {
                            "system": "MAVEN",
                            "name": "org.finos:leg",
                            "version": "0.1.0",
                        },
                        "publishedAt": "2026-01-05T12:00:00Z",
                    }
                ]
            }
        ),
        "https://repo1.maven.org/maven2/org/finos/leg/0.1.0/leg-0.1.0.pom": FakeResponse(
            text_data="<project><description>legacy path</description></project>"
        ),
    }
    context = build_context(fake)
    rels = crawl_maven(context)
    assert len(rels) == 1
    assert rels[0].artifact == "org.finos:leg"
    assert rels[0].description == "legacy path"


def test_crawl_maven_getversion_404_skips_candidate():
    fake = {
        _solr_gav_select_key(): FakeResponse(
            json_data={
                "response": {
                    "numFound": 1,
                    "docs": [
                        {
                            "g": "org.finos",
                            "a": "ghost",
                            "v": "1.0.0",
                            "p": "jar",
                            "timestamp": 1,
                        }
                    ],
                }
            }
        ),
        "https://api.deps.dev/v3/systems/maven/packages/org.finos%3Aghost/versions/1.0.0": FakeResponse(
            status_code=404, json_data={}
        ),
    }
    context = build_context(fake)
    assert crawl_maven(context) == []


def test_crawl_maven_solr_non_dict_json_falls_back_to_legacy_scan():
    fake = {
        _solr_gav_select_key(): FakeResponse(json_data=[]),
        (
            "https://search.maven.org/solrsearch/select",
            (
                ("core", "ga"),
                ("q", "g:org.finos*"),
                ("rows", 200),
                ("start", 0),
                ("wt", "json"),
            ),
        ): FakeResponse(
            json_data={
                "response": {
                    "numFound": 1,
                    "docs": [{"g": "org.finos", "a": "ndj", "latestVersion": "0.3.0"}],
                }
            }
        ),
        "https://api.deps.dev/v3/systems/maven/packages/org.finos%3Andj": FakeResponse(
            json_data={
                "versions": [
                    {
                        "versionKey": {
                            "system": "MAVEN",
                            "name": "org.finos:ndj",
                            "version": "0.3.0",
                        },
                        "publishedAt": "2026-01-05T12:00:00Z",
                    }
                ]
            }
        ),
        "https://repo1.maven.org/maven2/org/finos/ndj/0.3.0/ndj-0.3.0.pom": FakeResponse(
            text_data="<project><description>ndjson</description></project>"
        ),
    }
    context = build_context(fake)
    rels = crawl_maven(context)
    assert len(rels) == 1
    assert rels[0].artifact == "org.finos:ndj"


def test_crawl_maven_solr_hit_cap_falls_back_to_legacy_scan():
    fake = {
        _solr_gav_select_key(): FakeResponse(
            json_data={
                "response": {
                    "numFound": 30_000,
                    "docs": [
                        {
                            "g": "org.finos",
                            "a": "x",
                            "v": "9.9.9",
                            "p": "jar",
                            "timestamp": 1,
                        }
                    ],
                }
            }
        ),
        (
            "https://search.maven.org/solrsearch/select",
            (
                ("core", "ga"),
                ("q", "g:org.finos*"),
                ("rows", 200),
                ("start", 0),
                ("wt", "json"),
            ),
        ): FakeResponse(
            json_data={
                "response": {
                    "numFound": 1,
                    "docs": [{"g": "org.finos", "a": "cap", "latestVersion": "0.2.0"}],
                }
            }
        ),
        "https://api.deps.dev/v3/systems/maven/packages/org.finos%3Acap": FakeResponse(
            json_data={
                "versions": [
                    {
                        "versionKey": {
                            "system": "MAVEN",
                            "name": "org.finos:cap",
                            "version": "0.2.0",
                        },
                        "publishedAt": "2026-01-05T12:00:00Z",
                    }
                ]
            }
        ),
        "https://repo1.maven.org/maven2/org/finos/cap/0.2.0/cap-0.2.0.pom": FakeResponse(
            text_data="<project><description>cap fallback</description></project>"
        ),
    }
    context = build_context(fake)
    rels = crawl_maven(context)
    assert len(rels) == 1
    assert rels[0].artifact == "org.finos:cap"


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


def _pypi_user_packages_response_xml(rows: list[list[str]]) -> str:
    """Build an XML-RPC ``methodResponse`` payload for ``user_packages``.

    ``rows`` is the raw list-of-pairs PyPI returns: ``[[role, name], ...]``.
    """
    return xmlrpc.client.dumps((rows,), methodresponse=True)


def test_crawl_pypi():
    fake = {
        # XML-RPC discovery: ``user_packages("finos")`` lists every distribution
        # owned/maintained by the FINOS PyPI user.
        "https://pypi.org/pypi": FakeResponse(
            text_data=_pypi_user_packages_response_xml([["Owner", "artifact"]])
        ),
        "https://pypi.org/pypi/artifact/json": FakeResponse(
            json_data={
                "info": {
                    "version": "1.0.0",
                    "summary": "Sample Python wheel",
                    "author": "Ada Lovelace",
                    "maintainer": "Charles Babbage",
                },
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
    assert py[0].artifact == "artifact"
    assert py[0].description == "Sample Python wheel"
    assert py[0].publisher == "Ada Lovelace, Charles Babbage"


def test_crawl_pypi_skips_missing_package():
    fake = {
        "https://pypi.org/pypi": FakeResponse(
            text_data=_pypi_user_packages_response_xml([["Owner", "missing"]])
        ),
        "https://pypi.org/pypi/missing/json": FakeResponse(
            status_code=404, json_data={}
        ),
    }
    context = build_context(fake)
    assert crawl_pypi(context) == []


def test_crawl_pypi_returns_empty_when_user_packages_non_200():
    # PyPI sometimes returns 5xx for the legacy XML-RPC endpoint; the source
    # must contribute zero releases for that crawl rather than raising.
    fake = {
        "https://pypi.org/pypi": FakeResponse(status_code=502, text_data="bad gateway"),
    }
    context = build_context(fake)
    assert crawl_pypi(context) == []


def test_crawl_pypi_returns_empty_when_user_packages_body_is_not_xmlrpc():
    # The Fastly bot-challenge HTML page that broke the previous HTML scrape:
    # an HTTP 200 response whose body is HTML, not XML-RPC. Must not crash.
    fake = {
        "https://pypi.org/pypi": FakeResponse(
            text_data="<!DOCTYPE html><html><body>Client Challenge</body></html>"
        ),
    }
    context = build_context(fake)
    assert crawl_pypi(context) == []


def test_crawl_pypi_returns_empty_on_xmlrpc_fault():
    # XML-RPC ``<fault>`` envelope (e.g. unknown user) ⇒ zero releases, no raise.
    fault_xml = xmlrpc.client.dumps(
        xmlrpc.client.Fault(1, "no such user"),
        methodresponse=True,
    )
    fake = {
        "https://pypi.org/pypi": FakeResponse(text_data=fault_xml),
    }
    context = build_context(fake)
    assert crawl_pypi(context) == []


def test_crawl_pypi_iterates_every_returned_package_name():
    # Multi-package discovery: every name from the XML-RPC response is fed
    # into the per-package /pypi/<name>/json loop, deduplicated when the same
    # name appears under multiple roles (Owner + Maintainer).
    rows = [
        ["Owner", "alpha"],
        ["Maintainer", "alpha"],  # duplicate role, same name → still one fetch
        ["Owner", "beta"],
    ]

    def _meta(name: str, version: str, when: str) -> FakeResponse:
        return FakeResponse(
            json_data={
                "info": {"version": version, "summary": f"summary {name}"},
                "releases": {
                    version: [
                        {
                            "upload_time_iso_8601": when,
                            "url": f"https://pypi/{name}",
                        }
                    ]
                },
            }
        )

    fake = {
        "https://pypi.org/pypi": FakeResponse(
            text_data=_pypi_user_packages_response_xml(rows)
        ),
        "https://pypi.org/pypi/alpha/json": _meta(
            "alpha", "1.0.0", "2026-01-04T00:00:00Z"
        ),
        "https://pypi.org/pypi/beta/json": _meta(
            "beta", "2.1.0", "2026-01-05T00:00:00Z"
        ),
    }
    context = build_context(fake)
    py = crawl_pypi(context)
    assert sorted(p.artifact for p in py) == ["alpha", "beta"]
    assert all(p.source == "pypi" for p in py)


def test_maven_pom_description_non_200_returns_none():
    pom_url = _maven_pom_url("org.finos.demo", "lib", "1.0.0")
    client = FakeClient({pom_url: FakeResponse(status_code=404)})
    assert _maven_pom_description(client, "org.finos.demo", "lib", "1.0.0") is None


def test_maven_pom_description_strips_cdata():
    pom_url = _maven_pom_url("org.finos.demo", "lib", "1.0.0")
    client = FakeClient(
        {
            pom_url: FakeResponse(
                text_data=(
                    "<project><description>"
                    "<![CDATA[  Hello CDATA  ]]>"
                    "</description></project>"
                )
            )
        }
    )
    assert (
        _maven_pom_description(client, "org.finos.demo", "lib", "1.0.0")
        == "Hello CDATA"
    )


def test_maven_developer_labels_all_developers_in_pom():
    pom = """<project>
  <developers>
    <developer>
      <name>ACME</name>
    </developer>
    <developer>
      <name>Pat Lee</name>
      <id>plee</id>
    </developer>
  </developers>
</project>"""
    assert _maven_developer_labels_from_pom_text(pom) == ["ACME", "Pat Lee (plee)"]


def test_maven_contributors_label_parent_pom_developers():
    leaf_g, leaf_a, leaf_v = "org.finos.demo", "child", "1.0.0"
    parent_g, parent_a, parent_v = "org.finos.demo", "parent", "1.0.0"
    leaf_url = _maven_pom_url(leaf_g, leaf_a, leaf_v)
    parent_url = _maven_pom_url(parent_g, parent_a, parent_v)
    leaf_pom = f"""<project>
  <parent>
    <groupId>{parent_g}</groupId>
    <artifactId>{parent_a}</artifactId>
    <version>{parent_v}</version>
  </parent>
</project>"""
    parent_pom = """<project>
  <developers>
    <developer><name>Steve Heron</name></developer>
    <developer><name>Chris Stevenson</name></developer>
  </developers>
</project>"""
    client = FakeClient(
        {
            leaf_url: FakeResponse(text_data=leaf_pom),
            parent_url: FakeResponse(text_data=parent_pom),
        }
    )
    out = _maven_contributors_label(
        client, leaf_g, leaf_a, leaf_v, leaf_pom_text=leaf_pom
    )
    assert out == "Steve Heron, Chris Stevenson"


def test_maven_contributors_label_no_developers_returns_none():
    pom_url = _maven_pom_url("org.finos.demo", "solo", "1.0.0")
    client = FakeClient({pom_url: FakeResponse(text_data="<project/>")})
    assert _maven_contributors_label(client, "org.finos.demo", "solo", "1.0.0") is None


def test_maven_pom_description_http_error_returns_none():
    pom_url = _maven_pom_url("org.finos.demo", "lib", "1.0.0")

    class ErrClient:
        def get(self, *args, **kwargs):
            raise httpx.RequestError("x", request=httpx.Request("GET", pom_url))

    assert _maven_pom_description(ErrClient(), "org.finos.demo", "lib", "1.0.0") is None


def test_npm_version_description_invalid_json_returns_none():
    pkg = quote("@finos/pkg", safe="")
    ver = quote("1.0.0", safe="")
    url = f"https://registry.npmjs.org/{pkg}/{ver}"
    client = FakeClient({url: FakeResponse(text_data="not json")})
    assert _npm_version_description(client, "@finos/pkg", "1.0.0") is None
