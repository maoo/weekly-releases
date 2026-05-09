# Weekly Releases

> [!IMPORTANT]
> Check [FINOS 2026 Weekly releases](weekly_releases/2026)!

Weekly Releases is a Python ([uv](https://docs.astral.sh/uv/)-based) crawler that gathers FINOS-related releases from GitHub, Maven Central, npm, PyPI, and Docker Hub, using FINOS landscape metadata to label projects. It writes one **standalone HTML** file per ISO week under `releases/YYYY/WW.html` by default (collapsible sections per project), or **`--format md`** for Markdown at `releases/YYYY/WW.md` (see **[specs.md](specs.md)**).

The normative description of **time windows**, **GitHub authentication**, **sources**, **HTML/Markdown layout**, **release descriptions**, and **landscape mapping** is **[specs.md](specs.md)**. This README focuses on install, usage, and CI.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## Install

```bash
uv sync --all-extras
```

## Usage

Run scan and write any missing week files:

```bash
uv run weekly-releases
```

Dry run (current ISO week only, no file writes):

```bash
uv run weekly-releases --dry-run
```

Crawl **only** the ISO week that contains `--today` (or today) and write **that** week’s file (skips epoch backfill):

```bash
uv run weekly-releases --current-week
```

Markdown output instead of HTML:

```bash
uv run weekly-releases --format md
```

Specify output directory:

```bash
uv run weekly-releases --output-dir releases
```

Use a local landscape file for deterministic runs:

```bash
uv run weekly-releases --landscape-source ./landscape.yml
```

### GitHub API authentication (`GITHUB_TOKEN` / `GH_TOKEN`)

Listing org repositories and release feeds uses the GitHub REST API. Without authentication the anonymous quota is small and you may see **`403 rate limit exceeded`**.

Set a [personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token). For public `finos` data you typically need **no extra scopes** beyond default read access:

```bash
export GITHUB_TOKEN=ghp_...   # preferred name on GitHub Actions

uv run weekly-releases
```

**GitHub Actions:** the workflow receives **`GITHUB_TOKEN`** automatically for the job run.

## Lint

Check (matches CI):

```bash
uv run ruff check weekly_releases tests && uv run black --check weekly_releases tests
```

Apply Ruff fixes and Black formatting:

```bash
uv run ruff check --fix weekly_releases tests && uv run black weekly_releases tests
```

## Test and coverage

```bash
uv run pytest
```

(Coverage and the 90% floor are configured in `pyproject.toml`.)

## CI

`.github/workflows/weekly-scan.yml` runs **ruff + black**, **pytest**, then weekly (Monday UTC) **normal backfill** (no `--current-week`), fills any missing `releases/YYYY/WW.html` files since the epoch (default format), and commits changes when needed.
