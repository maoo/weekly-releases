# Specifications

These notes are the **authoritative** behavior reference for Weekly Releases (unless the implementation differs, in which case treat the code as ground truth until specs catch up). **[README.md](README.md)** covers installation, command examples, and CI wiring.

## Overview

Weekly Releases is a small Python tool (dependencies managed with [uv](https://docs.astral.sh/uv/)) that polls public registries for artifacts associated with the FINOS community. It correlates repositories and package identifiers with **[FINOS landscape](https://github.com/finos/finos-landscape)** cards—primarily via `landscape.yml` (remote URL by default; override with `--landscape-source`), including optional per-card **`maven_groupid`** values that map Maven **`groupId`** prefixes to the card **`name`**—so each released artifact is labeled with the landscape **`name`** as the human-readable **project** when a match exists.

**Outputs:** Reports live under `releases/YYYY/WW.<ext>`: year plus zero-padded ISO week number. The extension is **`WW.html`** by default (**`--format html`**) or **`WW.md`** when **`--format md`**. A week counts as **present** only if the file for the **selected** format exists (so switching format may backfill new files alongside older ones). Within each file, releases are **grouped by project** in collapsible sections (native `<details>` in HTML; embedded `<details>` in Markdown). Each release row is bucketed by its **release timestamp** (UTC), aligned to the ISO week that contains that instant. Weeks with no releases still get a stub file when backfill creates them.

After every **non–dry-run** scan (`scan` without **`--dry-run`**), the tool also writes **`releases/index.html`** (under **`--output-dir`**, default `releases`): a standalone HTML page that lists every **numeric-named year subdirectory** (sorted ascending), and under each year links to all **`WW.html`** files found in that folder (sorted by week number). Year folders with no matching HTML week files still appear, with a short empty notice. The index does not list **`*.md`** week files; it reflects HTML reports only (the default CI format). Relative links use `YYYY/WW.html` from the index page.

**Crawl modes at a glance:** you can **dry-run** the current week without writes, **overwrite only** the current week’s file (`--current-week`), or run **normal backfill** that fills missing weeks from a fixed epoch through today—precise UTC boundaries and edge cases are spelled out under *Time windows*.

The sections below expand the **CLI**, **time windows**, **sources**, **report output** (HTML default and Markdown option), **landscape mapping**, and **GitHub API** authentication.

## CLI

The entry point is the Typer app **`weekly-releases`** (see **`[project.scripts]`** in `pyproject.toml`). Typical invocation: `uv run weekly-releases` with optional flags.

| Flag | Role |
|------|------|
| **`--output-dir` / `-o`** | Directory under which `YYYY/WW.<ext>` files are written (default `releases`). |
| **`--today`** | Override “today” as an ISO date `YYYY-MM-DD` (anchors the current ISO week and backfill “through” date). |
| **`--dry-run`** | Crawl **only** the current ISO week; **no files** written. Prints a short summary and **one line per release** using the same text shape as Markdown list items (`Release.as_markdown_line()`), regardless of **`--format`**. |
| **`--current-week`** | With write mode, crawl that week and write **one** week file; **ignored** when combined with **`--dry-run`**. |
| **`--quiet`** | Suppresses **`[progress]`** lines only. |
| **`--landscape-source`** | Optional path or URL for `landscape.yml` (defaults to the FINOS landscape raw URL in code). |
| **`--format`** | `html` or `md` (default **`html`**). Compared after **trim + lower-case**; any other value exits **non-zero** with an error message. Controls file extension and renderer only; **`--dry-run`** console output is unchanged. |

**CI:** The scheduled GitHub Action runs the tool with defaults unless the workflow is edited, so week files are **`WW.html`** unless **`--format md`** is added there. The same run refreshes **`releases/index.html`** so the Action commit includes an up-to-date directory of HTML week pages when anything under the output directory changes.

## Time windows (date frames)

- **Anchor:** Weeks are tracked from a fixed **epoch date** (`2026-01-01` in code). Any ISO week from that Monday through “today” that does **not** yet have the output file for the active **`--format`** (`releases/YYYY/WW.html` or `releases/YYYY/WW.md`) is considered **missing** and eligible for backfill.

- **`--dry-run`:** Scans **only the ISO week that contains `--today` (or today)** — from that week’s **Monday 00:00 UTC** through the **earlier of** that week’s end boundary **or end-of-day UTC on that date**. Nothing is written.

- **`--current-week` (write mode, without `--dry-run`):** Uses the **same crawl window** as `--dry-run` for the ISO week containing `--today` (or today). Writes **exactly one** file: `releases/YYYY/WW.html` when **`--format html`** (default) or `releases/YYYY/WW.md` when **`--format md`** (creating or **replacing** it). Does **not** inspect the epoch or missing-week backfill; other gaps are left unchanged. Releases returned by sources are filtered so only timestamps falling in that ISO week appear in the file.

- **Normal write** (no `--dry-run`, no `--current-week`):
  - If **every** week from the epoch through today already has an output file for the selected format, the run **does nothing** (no network crawl).
  - Otherwise it computes **all missing weeks**, performs **one combined crawl** over the inclusive UTC range from the **start of the earliest missing ISO week** through the **earlier of** end-of-today (UTC) **or** the **end boundary of the latest missing ISO week**, collects releases from all sources, **buckets each release by its release timestamp’s ISO week**, and writes **one file per missing week** (weeks with no matching releases still get a file with an empty notice).

The GitHub Action runs on a schedule using **normal write / backfill** (not `--current-week`), so each run can fill several missing week files in one pass when needed. The workflow uses the tool’s **default** **`--format`** (**`html`**) unless changed.

## Sources

The list of package repositories to crawl is:

- GitHub Releases (`github.com/finos`)
- Maven Central — Solr **`core=gav`** query **`g:org.finos* AND timestamp:[…]`** (milliseconds, with a short **look-back buffer** before the crawl window start) lists **candidate** `(groupId, artifactId, version)` rows whose Central Solr **`timestamp`** falls in that range. **Authoritative** version **`publishedAt`** (UTC) still comes from **[deps.dev](https://deps.dev/)** via **GetVersion** (`…/packages/{group:artifact}/versions/{version}`), and releases are kept only when **`publishedAt`** lies inside the actual crawl **`[start, end]`** window (so Solr lag or the buffer cannot surface out-of-window versions in the report). **Fallback:** if Solr GAV discovery fails, returns malformed data, exceeds an internal hit cap, or returns **zero hits** in the timestamp window (common when GAV indexing lags behind Central for recent dates), the crawler reverts to enumerating every **`org.finos*`** coordinate with Solr **`core=ga`** and deps.dev **package** metadata (full version list) as before. POM excerpts still load from **`repo1.maven.org`**; artifact lines use **`groupId:artifactId`** and **`search.maven.org/artifact/…`** links.
- NpmJS — **`/-/v1/search`**, **`text=@finos`** (the **`scope:finos`** text query returns no results from the registry today). Paginates with **`from` / `size`** until all scoped hits are consumed.
- PyPI (`https://pypi.org/user/finos/`)
- Docker Hub (`https://hub.docker.com/u/finos`)

## Report output (HTML and Markdown)

- **`--format`:** `html` (default) emits a **standalone HTML document** with embedded CSS: readable typography, soft background, and one `<details class="project">` per project. **All project sections are collapsed by default** (no `open` attribute). Each `<summary>` shows the project name and a **release count** in parentheses. Releases are a `<ul>` of items with escaped text and an HTML link to the canonical URL. `md` emits **Markdown** with the same grouping using `<details>` / `<summary>` (GitHub-flavored rendering).

- **Structure (Markdown):** After the file title (`# FINOS releases for …`), each **project** block is a collapsible: `<details>` with `<summary>` set to the literal project label (HTML-escaped, for example Git Proxy). All release bullets for that project sit in the body between `<summary>…</summary>` and `</details>`. Section order is **ascending by project name**, compared case-insensitively; ties keep stable ordering by the original label. Within a section, releases are ordered by **`released_at`** (UTC), earliest first.

- **Structure (HTML):** A single page with `<title>` and `<h1>` matching the week label (`FINOS releases for {year} week {WW}`), a short subtitle, then the same **project ordering** and **`released_at`** ordering within each project as Markdown. All dynamic text is **HTML-escaped**. Empty weeks render a short **centered** notice (`No releases found in this period.`).

- **Release rows (Markdown):** Inside each `<details>` body, every release is a markdown list item (dash bullet). The bullet text encodes, in order: linked **GitHub** repository (backticks) or **—** when unknown; **source** id (`github`, `maven`, `npm`, `pypi`, `docker`); **artifact** identifier (backticks); **version** (backticks); release **date** (UTC calendar date); and a markdown **link** to the canonical URL. The project name is **not** repeated on the bullet line because it is already the `<summary>` label.

- **Release rows (HTML):** Each release is an `<li class="release">` inside the project’s `<ul>`. A single **meta** row (pipe-separated spans) carries the same fields in order: **GitHub** repo (monospace) or em dash; **source**; **artifact**; **version**; **date** (UTC calendar); and a visible **“link”** anchor to the canonical URL (`href` attribute escaped for HTML). Optional **description** appears below as a `<p class="description">`: content is escaped, newlines become `<br>`, and **`white-space: pre-wrap`** preserves layout where useful.

- **Project label:** Use the landscape card **`name`** when the release resolves to that card via repo URLs or asset keys (Landscape mapping). **Maven-only:** cards may declare **`maven_groupid`** in `landscape.yml` (string or list of strings). For Maven Central rows, when the coordinate’s **`groupId`** equals that value or starts with **`maven_groupid` + `"."`** (nested group IDs such as `org.finos.vuu.plugin` under `org.finos.vuu`), the release is labeled with that card’s **`name`**. If several prefixes match, the **longest** prefix wins. If nothing matches, resolution may use GitHub org repo association or, as a last resort, a title-cased artifact/repo slug. Labels such as **`Unknown`** still produce their own collapsible section when needed.

- **Optional description (Markdown):** When normalized descriptive text is available from the upstream source, the generator emits a **second line** immediately under that bullet, indented and prefixed with `Description:` followed by the excerpt.

- **Optional description (HTML):** When a description exists, it is appended under the meta row as described above; if not, the list item contains only the meta row.

- **Description provenance by source:**
  - **GitHub:** release `body` text.
  - **Maven:** the `<description>` element from the POM at Maven Central for the released artifact version.
  - **npm:** the `description` field from the registry JSON for the specific package **version** (not only the latest package metadata).
  - **PyPI:** `info.summary` if non-empty, otherwise `info.description`.
  - **Docker Hub:** repository `full_description` if non-empty, otherwise `description`.

- **Normalization:** descriptions are plain text **before** HTML escaping or Markdown emission. Markup is lightly stripped (including fenced code regions, backticks, and markdown links reduced to visible label text), whitespace is collapsed, and the stored excerpt length is capped at **300 Unicode characters**. Text beyond that limit is reduced using leading complete sentences when they fit; otherwise the excerpt ends at a word boundary with a trailing ellipsis (`…`). If no non-empty description remains after normalization, the release item has **only** the primary row (Markdown bullet line, or HTML meta row without a description paragraph).

## Landscape mapping

A FINOS project may contain multiple repositories and released artifacts; use  
`https://github.com/finos/finos-landscape/blob/main/landscape.yml` as the main source of project-to-repo and project-to-asset assignment (including nested `item.repo_url`, `additional_repos`, and `docker_hub` entries).

Many FINOS cards use a **null `item:` key** and place **`repo_url`**, **`additional_repos`**, and **`homepage_url`** (when it points at GitHub) as **siblings of `item`** on the same mapping. The crawler treats both that outer mapping and any nested `item` dict as sources for repo URLs so the landscape **`name`** on that card maps to every listed GitHub repo (for example **Rune** and `rune-dsl`). The same outer vs nested **`item`** surfaces are scanned for **`maven_groupid`** so Maven coordinates can resolve to the card even when no asset string or repo slug match exists.

Top-level landscape entries use **`category:`** as a **null marker** with **`name`** and **`subcategories`** as sibling keys; the walker must **not** recurse into that null value (it would skip the whole subtree). **Resolution:** once a release resolves to a GitHub org repo slug (`finos/…`), the project label prefers the landscape **`repo_to_project`** entry for that slug over title-cased fallbacks (and over **`maven_groupid`**-derived labels when both apply) so the reported name matches the card **`name`** that lists the repository.

## Quality and tooling

- The code is unit tested, with **90%+** test coverage.
- There is a **dry run** execution, runnable locally with uv.
- **`latest_weekly_file(output_dir)`** (library helper): returns the newest week report path under `output_dir` by choosing the **highest numeric year** subdirectory, then the **highest numeric week** stem among **`*.html`** and **`*.md`**. If both `WW.html` and `WW.md` exist for the same week, **`.html`** is preferred.
- **`write_releases_index(output_dir)`** (library helper): writes **`output_dir/index.html`** using **`collect_year_week_html_files`** / **`render_releases_index_html`** so navigation matches the on-disk year folders and **`WW.html`** reports.
- **README.md** documents install, usage (including env vars), testing, and CI.

## GitHub API authentication

GitHub org repo listing and per-repo release endpoints use the REST API. **Unauthenticated** requests hit a low rate limit and may return `403 rate limit exceeded`.

- Support **`GITHUB_TOKEN`** or **`GH_TOKEN`** (same convention as the GitHub CLI). Headers for GitHub are attached **per request to `api.github.com` only**, not on the shared HTTP client defaults: **`Accept: application/vnd.github+json`** is always sent on those requests; **`Authorization: Bearer <token>`** is added when a token is set. Crawls against npm, Maven, PyPI, Docker Hub, and the landscape YAML URL therefore **never** receive GitHub `Accept` / `Authorization` headers (avoiding registry errors such as HTTP **406** from npm when a GitHub-only `Accept` would be forwarded).
- **GitHub Actions** injects **`GITHUB_TOKEN`** automatically for the job (no extra secret required for typical public-org reads).