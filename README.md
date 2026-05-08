# Weekly Releases

> [!IMPORTANT]
> Check [FINOS 2026 Weekly releases](weekly_releases/2026)!

Weekly Releases is a Python ([uv](https://docs.astral.sh/uv/)-based) crawler that gathers FINOS-related releases from GitHub, Maven Central, npm, PyPI, and Docker Hub, using FINOS landscape metadata to label projects. It writes one markdown file per ISO week under `releases/YYYY/WW.md`, with releases **grouped under `## Project name` headings** inside each file (see **[specs.md](specs.md)**).

The normative description of **time windows**, **GitHub authentication**, **sources**, **markdown layout**, **release descriptions**, and **landscape mapping** is **[specs.md](specs.md)**. This README focuses on install, usage, and CI.

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

## Test and coverage

```bash
uv run pytest
```

The test suite enforces at least 90% code coverage.

## CI

`.github/workflows/weekly-scan.yml` runs weekly (Monday UTC) with **normal backfill** (no `--current-week`), fills any missing `releases/YYYY/WW.md` files since the epoch, and commits changes when needed.
