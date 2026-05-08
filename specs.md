# Specifications

These notes are the **authoritative** behavior reference for Weekly Releases (unless the implementation differs, in which case treat the code as ground truth until specs catch up). **[README.md](README.md)** covers installation, command examples, and CI wiring.

## Overview

Weekly Releases is a small Python tool (dependencies managed with [uv](https://docs.astral.sh/uv/)) that polls public registries for artifacts associated with the FINOS community. It correlates repositories and package identifiers with **[FINOS landscape](https://github.com/finos/finos-landscape)** cards—primarily via `landscape.yml` (remote URL by default; override with `--landscape-source`)—so each released artifact is labeled with the landscape **`name`** as the human-readable **project** when a match exists.

**Outputs:** Reports live under `releases/YYYY/WW.md`: year plus zero-padded ISO week number. Within a file, releases are **grouped under `## <project>` section headings** (see *Markdown output and descriptions*). Each release row is bucketed by its **release timestamp** (UTC), aligned to the ISO week that contains that instant. Weeks with no releases still get a stub file when backfill creates them.

**Crawl modes at a glance:** you can **dry-run** the current week without writes, **overwrite only** the current week’s file (`--current-week`), or run **normal backfill** that fills missing weeks from a fixed epoch through today—precise UTC boundaries and edge cases are spelled out under *Time windows*.

The sections below expand sources, markdown formatting (including optional **`Description:`** lines), landscape mapping quirks (for example `repo_url` beside a null `item:`), and GitHub API auth details.

## Time windows (date frames)

- **Anchor:** Weeks are tracked from a fixed **epoch date** (`2026-01-01` in code). Any ISO week from that Monday through “today” that does **not** yet have a `releases/YYYY/WW.md` file is considered **missing** and eligible for backfill.

- **`--dry-run`:** Scans **only the ISO week that contains `--today` (or today)** — from that week’s **Monday 00:00 UTC** through the **earlier of** that week’s end boundary **or end-of-day UTC on that date**. Nothing is written.

- **`--current-week` (write mode, without `--dry-run`):** Uses the **same crawl window** as `--dry-run` for the ISO week containing `--today` (or today). Writes **exactly one** file: `releases/YYYY/WW.md` for that week (creating or **replacing** it). Does **not** inspect the epoch or missing-week backfill; other gaps are left unchanged. Releases returned by sources are filtered so only timestamps falling in that ISO week appear in the file.

- **Normal write** (no `--dry-run`, no `--current-week`):
  - If **every** week from the epoch through today already has a markdown file, the run **does nothing** (no network crawl).
  - Otherwise it computes **all missing weeks**, performs **one combined crawl** over the inclusive UTC range from the **start of the earliest missing ISO week** through the **earlier of** end-of-today (UTC) **or** the **end boundary of the latest missing ISO week**, collects releases from all sources, **buckets each release by its release timestamp’s ISO week**, and writes **one file per missing week** (weeks with no matching releases still get a file with an empty notice).

The GitHub Action runs on a schedule using **normal write / backfill** (not `--current-week`), so each run can fill several missing week files in one pass when needed.

## Sources

The list of package repositories to crawl is:

- GitHub Releases (`github.com/finos`)
- Maven Central — Solr **`core=ga`** query **`g:org.finos*`** lists every **unique** coordinate whose **`groupId` starts with `org.finos`** (including nested IDs such as `org.finos.symphony.bdk`). Version-level **release timestamps** come from the **[deps.dev](https://deps.dev/)** Maven package API (`publishedAt` per version), because **`search.maven.org` `core=gav` timestamps often lag Central by months** and would otherwise drop recent releases. POM excerpts still load from **`repo1.maven.org`** (group path segments); artifact lines use **`groupId:artifactId`** and **`search.maven.org/artifact/…`** links.
- NpmJS — **`/-/v1/search`**, **`text=@finos`** (the **`scope:finos`** text query returns no results from the registry today). Paginates with **`from` / `size`** until all scoped hits are consumed.
- PyPI (`https://pypi.org/user/finos/`)
- Docker Hub (`https://hub.docker.com/u/finos`)

## Markdown output and descriptions

- **Structure:** After the file title (`# FINOS releases for …`), releases sharing the same **project** string appear together under a second-level heading **`## <project>`** (literal project label, for example `## Git Proxy`). Section order is **ascending by project name**, compared case-insensitively; ties keep stable ordering by the original label. Within a section, releases are ordered by **`released_at`** (UTC), earliest first.

- **Release rows:** Under each `##` heading, every release is a markdown list item (dash bullet). The bullet text encodes, in order: linked **GitHub** repository (backticks) or **—** when unknown; **source** id (`github`, `maven`, `npm`, `pypi`, `docker`); **artifact** identifier (backticks); **version** (backticks); release **date** (UTC calendar date); and a markdown **link** to the canonical URL. The project name is **not** repeated on the bullet line because it is already the section heading.

- **Project label:** Use the landscape card **`name`** when the release resolves to that card via repo URLs or asset keys (Landscape mapping). If nothing matches, resolution may use GitHub org repo association or, as a last resort, a title-cased artifact/repo slug. Labels such as **`Unknown`** still produce their own `## Unknown` section when needed.

- **Optional description:** When normalized descriptive text is available from the upstream source, the generator emits a **second line** immediately under that bullet, indented and prefixed with `Description:` followed by the excerpt.

- **Description provenance by source:**
  - **GitHub:** release `body` text.
  - **Maven:** the `<description>` element from the POM at Maven Central for the released artifact version.
  - **npm:** the `description` field from the registry JSON for the specific package **version** (not only the latest package metadata).
  - **PyPI:** `info.summary` if non-empty, otherwise `info.description`.
  - **Docker Hub:** repository `full_description` if non-empty, otherwise `description`.

- **Normalization:** descriptions are plain text in the output file. Markup is lightly stripped (including fenced code regions, backticks, and markdown links reduced to visible label text), whitespace is collapsed, and the stored excerpt length is capped at **300 Unicode characters**. Text beyond that limit is reduced using leading complete sentences when they fit; otherwise the excerpt ends at a word boundary with a trailing ellipsis (`…`). If no non-empty description remains after normalization, the release item has **only** the primary bullet line.

## Landscape mapping

A FINOS project may contain multiple repositories and released artifacts; use  
`https://github.com/finos/finos-landscape/blob/main/landscape.yml` as the main source of project-to-repo and project-to-asset assignment (including nested `item.repo_url`, `additional_repos`, and `docker_hub` entries).

Many FINOS cards use a **null `item:` key** and place **`repo_url`**, **`additional_repos`**, and **`homepage_url`** (when it points at GitHub) as **siblings of `item`** on the same mapping. The crawler treats both that outer mapping and any nested `item` dict as sources for repo URLs so the landscape **`name`** on that card maps to every listed GitHub repo (for example **Rune** and `rune-dsl`).

Top-level landscape entries use **`category:`** as a **null marker** with **`name`** and **`subcategories`** as sibling keys; the walker must **not** recurse into that null value (it would skip the whole subtree). **Resolution:** once a release resolves to a GitHub org repo slug (`finos/…`), the project label prefers the landscape **`repo_to_project`** entry for that slug over title-cased fallbacks so the reported name matches the card **`name`** that lists the repository.

## Quality and tooling

- The code is unit tested, with **90%+** test coverage.
- There is a **dry run** execution, runnable locally with uv.
- **README.md** documents install, usage (including env vars), testing, and CI.

## GitHub API authentication

GitHub org repo listing and per-repo release endpoints use the REST API. **Unauthenticated** requests hit a low rate limit and may return `403 rate limit exceeded`.

- Support **`GITHUB_TOKEN`** or **`GH_TOKEN`** (same convention as the GitHub CLI). Headers for GitHub are attached **per request to `api.github.com` only**, not on the shared HTTP client defaults: **`Accept: application/vnd.github+json`** is always sent on those requests; **`Authorization: Bearer <token>`** is added when a token is set. Crawls against npm, Maven, PyPI, Docker Hub, and the landscape YAML URL therefore **never** receive GitHub `Accept` / `Authorization` headers (avoiding registry errors such as HTTP **406** from npm when a GitHub-only `Accept` would be forwarded).
- **GitHub Actions** injects **`GITHUB_TOKEN`** automatically for the job (no extra secret required for typical public-org reads).