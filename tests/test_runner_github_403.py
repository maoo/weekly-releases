import httpx
import pytest
from weekly_releases.runner import fetch_all_finos_repo_names


def test_fetch_repos_raises_helpful_error_on_403_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    class Client:
        def get(self, url: str, headers=None):
            return httpx.Response(
                403, request=httpx.Request("GET", url), json={"message": "rate limit"}
            )

    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        fetch_all_finos_repo_names(Client())


def test_fetch_repos_reraises_403_when_token_configured(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "pat-token")

    class Client:
        def get(self, url: str, headers=None):
            return httpx.Response(403, request=httpx.Request("GET", url))

    with pytest.raises(httpx.HTTPStatusError):
        fetch_all_finos_repo_names(Client())
