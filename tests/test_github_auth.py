from weekly_releases import github_auth


def test_github_token_prefers_github_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gh_token_a")
    monkeypatch.setenv("GH_TOKEN", "gh_token_b")
    assert github_auth.github_token_from_env() == "gh_token_a"


def test_github_token_falls_back_to_gh_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "from_gh")
    assert github_auth.github_token_from_env() == "from_gh"


def test_github_api_headers_without_token_sets_accept_only(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert github_auth.github_api_headers() == {"Accept": "application/vnd.github+json"}


def test_github_api_headers_with_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    h = github_auth.github_api_headers()
    assert h["Authorization"] == "Bearer secret"
    assert h["Accept"] == "application/vnd.github+json"
