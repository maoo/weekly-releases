"""GitHub REST API authentication via environment variables."""

from __future__ import annotations

import os

# GITHUB_TOKEN is standard (including GitHub Actions). GH_TOKEN matches the gh CLI.
_ENV_KEYS = ("GITHUB_TOKEN", "GH_TOKEN")


def github_token_from_env() -> str | None:
    for key in _ENV_KEYS:
        val = os.environ.get(key)
        if val and val.strip():
            return val.strip()
    return None


def github_api_headers() -> dict[str, str]:
    """Headers for ``api.github.com`` requests only.

    Do **not** attach these on a shared :class:`httpx.Client` used for other hosts:
    npm, Maven, PyPI, and Docker reject GitHub's ``Accept`` value with HTTP 406.
    """
    headers = {"Accept": "application/vnd.github+json"}
    token = github_token_from_env()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_auth_configured() -> bool:
    return github_token_from_env() is not None
