from typer.testing import CliRunner

from weekly_releases.cli import app


def test_cli_dry_run(monkeypatch):
    runner = CliRunner()

    class _Result:
        output_files: list = []
        releases: list = []

    def _run(**kwargs):
        kwargs["progress"]("test-step")
        return _Result()

    monkeypatch.setattr("weekly_releases.cli.run", _run)
    result = runner.invoke(app, ["--today", "2026-01-08", "--dry-run"])
    assert result.exit_code == 0
    assert "[progress]" in result.stdout
    assert "Dry run: collected 0 releases for the current week" in result.stdout


def test_cli_write_mode_with_missing_weeks(monkeypatch, tmp_path):
    runner = CliRunner()

    file_a = tmp_path / "01.md"
    file_b = tmp_path / "02.md"

    class _Result:
        output_files = [file_a, file_b]
        releases = [1, 2, 3]

    monkeypatch.setattr("weekly_releases.cli.run", lambda **kwargs: _Result())
    result = runner.invoke(app, ["--today", "2026-01-08"])
    assert result.exit_code == 0
    assert "Wrote 3 releases across 2 week(s):" in result.stdout
    assert str(file_a) in result.stdout
    assert str(file_b) in result.stdout


def test_cli_write_mode_no_missing_weeks(monkeypatch):
    runner = CliRunner()

    class _Result:
        output_files: list = []
        releases: list = []

    monkeypatch.setattr("weekly_releases.cli.run", lambda **kwargs: _Result())
    result = runner.invoke(app, ["--today", "2026-01-08"])
    assert result.exit_code == 0
    assert "No missing weeks; nothing written." in result.stdout


def test_cli_current_week(monkeypatch, tmp_path):
    runner = CliRunner()

    out_file = tmp_path / "2026" / "19.md"

    class _Result:
        output_files = [out_file]
        releases = [1, 2]

    monkeypatch.setattr("weekly_releases.cli.run", lambda **kwargs: _Result())
    result = runner.invoke(app, ["--today", "2026-05-09", "--current-week"])
    assert result.exit_code == 0
    assert "Current week: wrote 2 releases to" in result.stdout
    assert str(out_file) in result.stdout


def test_cli_quiet_mode(monkeypatch):
    runner = CliRunner()

    class _Result:
        output_files: list = []
        releases: list = []

    def _run(**kwargs):
        kwargs["progress"]("test-step")
        return _Result()

    monkeypatch.setattr("weekly_releases.cli.run", _run)
    result = runner.invoke(app, ["--today", "2026-01-08", "--quiet"])
    assert result.exit_code == 0
    assert "[progress]" not in result.stdout
