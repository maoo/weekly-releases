from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

LANDSCAPE_URL = "https://raw.githubusercontent.com/finos/finos-landscape/main/landscape.yml"

_ASSET_KEYS = ("maven", "npm", "pypi", "docker", "packages", "artifacts", "docker_hub")


@dataclass(slots=True)
class LandscapeIndex:
    repo_to_project: dict[str, str] = field(default_factory=dict)
    asset_to_project: dict[str, str] = field(default_factory=dict)
    asset_to_repo: dict[str, str] = field(default_factory=dict)

    def project_for_repo(self, repo: str) -> str:
        return self.repo_to_project.get(repo, "Unknown")

    def project_for_asset(self, asset: str) -> str:
        return self.asset_to_project.get(asset, "Unknown")

    def repo_for_asset(self, asset: str) -> str | None:
        return self.asset_to_repo.get(asset)


def _item_dict(node: dict[str, Any]) -> dict[str, Any]:
    item = node.get("item")
    return item if isinstance(item, dict) else {}


def _repo_name_from_url(url: str) -> str | None:
    if "github.com/" not in url:
        return None
    tail = url.split("github.com/", maxsplit=1)[1]
    parts = [p for p in tail.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    return parts[1]


def _repo_urls_from_node(node: dict[str, Any]) -> list[str]:
    """Collect repo URLs from both the card dict and nested ``item``.

    FINOS landscape cards often use ``item:`` with no nested mapping and put
    ``repo_url`` / ``additional_repos`` / ``homepage_url`` alongside ``item`` as
    siblings on the same mapping — those live on ``node``, not inside ``item``.
    """
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        if url not in seen:
            seen.add(url)
            urls.append(url)

    containers: list[dict[str, Any]] = []
    if isinstance(node, dict):
        containers.append(node)
        item = _item_dict(node)
        if item:
            containers.append(item)

    for container in containers:
        ru = container.get("repo_url")
        if isinstance(ru, str):
            add(ru)
        for entry in container.get("additional_repos", []) or []:
            if isinstance(entry, dict):
                u = entry.get("repo_url")
                if isinstance(u, str):
                    add(u)
        homepage = container.get("homepage_url")
        if isinstance(homepage, str) and "github.com/" in homepage:
            add(homepage)
    return urls


def _collect_from_asset_fields(container: dict[str, Any]) -> list[str]:
    assets: list[str] = []
    for key in _ASSET_KEYS:
        value = container.get(key)
        if isinstance(value, str):
            assets.append(value)
        elif isinstance(value, list):
            assets.extend(str(x) for x in value if isinstance(x, (str, int, float)))
    return assets


def _expand_asset_keys(raw: str) -> list[str]:
    """Normalize FINOS landscape/docker_hub quirks into lookup keys."""
    s = " ".join(raw.split()).strip()
    keys: list[str] = []
    seen: set[str] = set()

    def add(k: str) -> None:
        k = k.strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)

    add(s)
    parts = s.split()
    if len(parts) >= 2 and parts[0].lower() == "finos":
        image = parts[1].lstrip("/")
        add(f"finos/{image}")
        add(image)
    return keys


def _pick_repo_for_asset_key(asset_key: str, repo_slugs: set[str]) -> str | None:
    if asset_key in repo_slugs:
        return asset_key
    short = asset_key
    if asset_key.startswith("finos/"):
        short = asset_key.split("/", 1)[1]
    elif "/" in asset_key:
        short = asset_key.split("/")[-1]
    if short in repo_slugs:
        return short
    best: str | None = None
    best_len = -1
    for r in repo_slugs:
        if short == r or short.startswith(r + "-"):
            if len(r) > best_len:
                best = r
                best_len = len(r)
    return best


def _register_node_with_project(node: dict[str, Any], project: str, index: LandscapeIndex) -> None:
    repo_slugs: set[str] = set()
    for url in _repo_urls_from_node(node):
        slug = _repo_name_from_url(url)
        if slug:
            repo_slugs.add(slug)
            index.repo_to_project[slug] = project

    containers = [node, _item_dict(node)]
    raw_assets: list[str] = []
    for c in containers:
        raw_assets.extend(_collect_from_asset_fields(c))

    seen_lookup_keys: set[str] = set()
    for raw in raw_assets:
        for key in _expand_asset_keys(raw):
            if key in seen_lookup_keys:
                continue
            seen_lookup_keys.add(key)
            index.asset_to_project[key] = project
            guessed = _pick_repo_for_asset_key(key, repo_slugs)
            if guessed:
                index.asset_to_repo[key] = guessed


def _walk_landscape(node: Any, parent_project: str | None, index: LandscapeIndex) -> None:
    if isinstance(node, list):
        for el in node:
            _walk_landscape(el, parent_project, index)
        return
    if not isinstance(node, dict):
        return

    # FINOS ``landscape.yml`` uses ``category:`` as a null sibling marker; only recurse when it is
    # a real mapping. Otherwise we would visit ``None`` and skip ``subcategories`` / ``items``.
    cat = node.get("category")
    if isinstance(cat, dict):
        _walk_landscape(cat, None, index)
        return

    name = node.get("name") if isinstance(node.get("name"), str) else None
    has_repo = bool(_repo_urls_from_node(node))

    display_project = parent_project if parent_project is not None else name

    if display_project and has_repo:
        _register_node_with_project(node, display_project, index)

    child_parent = name if has_repo else parent_project

    subs = node.get("subcategories")
    if subs:
        _walk_landscape(subs, None, index)
    items = node.get("items")
    if items:
        _walk_landscape(items, child_parent, index)


def parse_landscape(raw_yaml: str) -> LandscapeIndex:
    content = yaml.safe_load(raw_yaml) or {}
    root: Any = content.get("landscape", []) if isinstance(content, dict) else []
    index = LandscapeIndex()
    _walk_landscape(root, None, index)
    return index


def load_landscape(source: str | None = None) -> LandscapeIndex:
    if source is None:
        response = httpx.get(LANDSCAPE_URL, timeout=30.0)
        response.raise_for_status()
        text = response.text
    else:
        maybe_file = Path(source)
        if maybe_file.exists():
            text = maybe_file.read_text(encoding="utf-8")
        else:
            response = httpx.get(source, timeout=30.0)
            response.raise_for_status()
            text = response.text
    return parse_landscape(text)
