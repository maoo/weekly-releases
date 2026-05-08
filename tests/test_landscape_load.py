from pathlib import Path

from weekly_releases.landscape import load_landscape


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def test_load_landscape_from_file(tmp_path: Path):
    f = tmp_path / "landscape.yml"
    f.write_text("landscape:\n  items: []\n", encoding="utf-8")
    idx = load_landscape(str(f))
    assert idx.repo_to_project == {}


def test_load_landscape_from_url(monkeypatch):
    monkeypatch.setattr("weekly_releases.landscape.httpx.get", lambda *args, **kwargs: _Resp("landscape:\n  items: []\n"))
    idx = load_landscape("https://example.test/landscape.yml")
    assert idx.asset_to_project == {}


def test_load_landscape_default_url(monkeypatch):
    monkeypatch.setattr("weekly_releases.landscape.httpx.get", lambda *args, **kwargs: _Resp("landscape:\n  items: []\n"))
    idx = load_landscape()
    assert idx.repo_to_project == {}

