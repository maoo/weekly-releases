# Specifications

These notes are the **authoritative** behavior reference for Weekly Releases (unless the implementation differs, in which case treat the code as ground truth until specs catch up). **[README.md](README.md)** covers installation, command examples, and CI wiring.

## Overview

Weekly Releases is a small Python tool (dependencies managed with [uv](https://docs.astral.sh/uv/)) that polls public registries for artifacts associated with the FINOS community. It correlates repositories and package identifiers with **[FINOS landscape](https://github.com/finos/finos-landscape)** cards—primarily via `landscape.yml` (remote URL by default; override with `--landscape-source`), including optional per-card **`maven_groupid`** values that map Maven **`groupId`** prefixes to the card **`name`**—so each released artifact is labeled with the landscape **`name`** as the human-readable **project** when a match exists.

**Outputs:** Reports live under `docs/YYYY/WW.<ext>`: year plus zero-padded ISO week number. The extension is **`WW.html`** by default (**`--format html`**) or **`WW.md`** when **`--format md`**. A week counts as **present** only if the file for the **selected** format exists (so switching format may backfill new files alongside older ones). Within each file, releases are **grouped by project** in collapsible sections (native `<details>` in HTML; embedded `<details>` in Markdown). Each release row is bucketed by its **release timestamp** (UTC), aligned to the ISO week that contains that instant. Weeks with no releases still get a stub file when backfill creates them. When **`--format html`**, the same folder may also contain **`calendar-YYYY-MM.html`** (Gregorian year-month) files produced with the index (see *Index and calendar month pages* below); they are not used as crawl inputs.

After every **non–dry-run** scan (`scan` without **`--dry-run`**), the tool writes **`docs/index.html`** (under **`--output-dir`**, default `docs`): a standalone HTML page titled **FINOS Releases** that lists every **numeric-named ISO week-year subdirectory** with **`Y ≥ 2026`** (sorted ascending; older year folders are omitted from the index). For each listed year, the page offers two views: **By month** (Gregorian month headings such as “January 2026”, each linking to a **single** rollup page) and **By week** (a flat list of **`WW.html`** links). **By month** targets **`YYYY/calendar-YYYY-MM.html`** (Gregorian **`YYYY-MM`** in the filename). **`--dry-run`** does **not** write or update the index or calendar files.

The index and calendar rollups are described in *Index and calendar month pages* below. In short: calendar pages aggregate **`WW.html`** in the same ISO year folder whose week’s **Thursday** falls in that month, **By week** lists **`WW.html`** sorted by week number, and the index does not list **`*.md`** week files. If the output tree has only pre-2026 week HTML, the index shows a single notice that nothing is listed for 2026 onward yet. Relative links use `YYYY/WW.html` (by week) or `YYYY/calendar-YYYY-MM.html` (by month) from the index page.

**Crawl modes at a glance:** you can **dry-run** the current week without writes, **overwrite only** the current week’s file (`--current-week`), or run **normal backfill** that fills missing weeks from a fixed epoch through today—precise UTC boundaries and edge cases are spelled out under *Time windows*.

The sections below expand the **CLI**, **time windows**, **sources**, **report output** (HTML default and Markdown option), **landscape mapping**, and **GitHub API** authentication.

## CLI

The entry point is the Typer app **`weekly-releases`** (see **`[project.scripts]`** in `pyproject.toml`). Typical invocation: `uv run weekly-releases` with optional flags.

| Flag | Role |
|------|------|
| **`--output-dir` / `-o`** | Directory under which `YYYY/WW.<ext>` files are written (default `docs`). |
| **`--today`** | Override “today” as an ISO date `YYYY-MM-DD` (anchors the current ISO week and backfill “through” date). |
| **`--dry-run`** | Crawl **only** the current ISO week; **no files** written (no week reports, **`index.html`**, or **`calendar-*.html`** updates). Prints a short summary and **one line per release** using the same text shape as Markdown list items (`Release.as_markdown_line()`), regardless of **`--format`**. |
| **`--current-week`** | With write mode, crawl that week and write **one** week file; **ignored** when combined with **`--dry-run`**. Afterward, **`index.html`** and **`calendar-*.html`** are regenerated the same way as in a normal write (so navigation picks up the new week HTML). |
| **`--quiet`** | Suppresses **`[progress]`** lines only. |
| **`--landscape-source`** | Optional path or URL for `landscape.yml` (defaults to the FINOS landscape raw URL in code). |
| **`--format`** | `html` or `md` (default **`html`**). Compared after **trim + lower-case**; any other value exits **non-zero** with an error message. Controls file extension and renderer only; **`--dry-run`** console output is unchanged. |

**CI:** The scheduled GitHub Action runs the tool with defaults unless the workflow is edited, so week files are **`WW.html`** unless **`--format md`** is added there. Each successful non–dry-run job refreshes the **current ISO week** report when needed (see *Time windows* → normal write), regenerates **`docs/index.html`**, and regenerates **`docs/YYYY/calendar-YYYY-MM.html`** rollups from on-disk **`WW.html`** so commits include up-to-date week, month, and index navigation whenever the output tree changes.

## Time windows (date frames)

- **Anchor:** Weeks are tracked from a fixed **epoch date** (`2026-01-01` in code). Any ISO week from that Monday through “today” that does **not** yet have the output file for the active **`--format`** (`docs/YYYY/WW.html` or `docs/YYYY/WW.md`) is considered **missing** and eligible for backfill.

- **`--dry-run`:** Scans **only the ISO week that contains `--today` (or today)** — from that week’s **Monday 00:00 UTC** through the **earlier of** that week’s end boundary **or end-of-day UTC on that date**. Nothing is written.

- **`--current-week` (write mode, without `--dry-run`):** Uses the **same crawl window** as `--dry-run` for the ISO week containing `--today` (or today). Writes **exactly one** file: `docs/YYYY/WW.html` when **`--format html`** (default) or `docs/YYYY/WW.md` when **`--format md`** (creating or **replacing** it). Does **not** inspect the epoch or missing-week backfill; other gaps are left unchanged. Releases returned by sources are filtered so only timestamps falling in that ISO week appear in the file.

- **Normal write** (no `--dry-run`, no `--current-week`):
  - If **every** week from the epoch through today already has an output file for the selected format, the run **skips backfill** (no gap-filling crawl) but still **re-crawls the ISO week containing `--today` (or today)**, **overwrites that week’s report file**, then **regenerates** **`index.html`** and **`YYYY/calendar-YYYY-MM.html`** month rollups so the latest week and month views stay current.
  - Otherwise it computes **all missing weeks**, performs **one combined crawl** over the inclusive UTC range from the **start of the earliest missing ISO week** through the **earlier of** end-of-today (UTC) **or** the **end boundary of the latest missing ISO week**, collects releases from all sources, **buckets each release by its release timestamp’s ISO week**, and writes **one file per missing week** (weeks with no matching releases still get a file with an empty notice). If the ISO week containing today was **not** among those missing files, the run performs an **additional** narrow crawl for that current week only and overwrites its report so it is never left stale between backfills.

The GitHub Action runs on a schedule using **normal write / backfill** (not `--current-week`), so each run can fill several missing week files in one pass when needed. The workflow uses the tool’s **default** **`--format`** (**`html`**) unless changed.

## Sources

The list of package repositories to crawl is:

- GitHub Releases (`github.com/finos`)
- Maven Central — Solr **`core=gav`** query **`g:org.finos* AND timestamp:[…]`** (milliseconds, with a short **look-back buffer** before the crawl window start) lists **candidate** `(groupId, artifactId, version)` rows whose Central Solr **`timestamp`** falls in that range. **Authoritative** version **`publishedAt`** (UTC) still comes from **[deps.dev](https://deps.dev/)** via **GetVersion** (`…/packages/{group:artifact}/versions/{version}`), and releases are kept only when **`publishedAt`** lies inside the actual crawl **`[start, end]`** window (so Solr lag or the buffer cannot surface out-of-window versions in the report). **Fallback:** if Solr GAV discovery fails, returns malformed data, exceeds an internal hit cap, or returns **zero hits** in the timestamp window (common when GAV indexing lags behind Central for recent dates), the crawler reverts to enumerating every **`org.finos*`** coordinate with Solr **`core=ga`** and deps.dev **package** metadata (full version list) as before. POMs load from **`repo1.maven.org`** (artifact POM plus **parent** POMs for contributor metadata); artifact lines use **`groupId:artifactId`** and **`search.maven.org/artifact/…`** links.
- NpmJS — **`/-/v1/search`**, **`text=@finos`** (the **`scope:finos`** text query returns no results from the registry today). Paginates with **`from` / `size`** until all scoped hits are consumed.
- PyPI (`https://pypi.org/user/finos/`)
- Docker Hub (`https://hub.docker.com/u/finos`)

## Report output (HTML and Markdown)

- **`--format`:** `html` (default) emits a **standalone HTML document** with embedded CSS: readable typography, soft background, and one `<details class="project">` per project. **All project sections are collapsed by default** (no `open` attribute). Each `<summary>` shows the project name and a **release count** in parentheses. Releases are a `<ul>` of items with escaped text and an HTML link to the canonical URL. `md` emits **Markdown** with the same grouping using `<details>` / `<summary>` (GitHub-flavored rendering).

- **Structure (Markdown):** After the file title (`# FINOS releases for …`), each **project** block is a collapsible: `<details>` with `<summary>` set to the literal project label (HTML-escaped, for example Git Proxy). All release bullets for that project sit in the body between `<summary>…</summary>` and `</details>`. Section order is **ascending by project name**, compared case-insensitively; ties keep stable ordering by the original label. Within a section, releases are ordered by **`released_at`** (UTC), earliest first.

- **Structure (HTML):** A single page with `<title>` and `<h1>` matching the week label (`FINOS releases for {year} week {WW}`), a short subtitle, then the same **project ordering** and **`released_at`** ordering within each project as Markdown. All dynamic text is **HTML-escaped**. Empty weeks render a short **centered** notice (`No releases found in this period.`).

- **Index and calendar month pages (HTML):** On every successful **`scan`** write (normal backfill or **`--current-week`**, not **`--dry-run`**), the library **first** regenerates **`YYYY/calendar-YYYY-MM.html`** under each ISO week-year folder **`Y ≥ 2026`** from existing **`WW.html`**, **then** writes **`index.html`**. The index **By month** column links to those calendar pages; **By week** links to **`YYYY/WW.html`**. Calendar files are **not** produced by a separate registry crawl: the implementation **reads existing weekly `render_html` output**, finds each `<details class="project">` … `<ul class="releases">` block and each `<li class="release">`, merges rows that share the same project **summary** label (after stripping the count span), and **sorts** `<li>` rows by the **UTC calendar date** embedded in each row’s meta line. The document shell (CSS, layout) matches weekly HTML except the title becomes **`FINOS releases for {Month Name} {Gregorian year}`** and the subtitle explains the aggregation. **Only `WW.html`** files participate; if a tree uses **`--format md`** only, week HTML is absent and those weeks do not contribute to calendar rollups (the index still lists only numeric **`*.html`** week stems).

- **Release rows (Markdown):** Inside each `<details>` body, every release is a markdown list item (dash bullet). The bullet text encodes, in order: linked **GitHub** repository (backticks) or **—** when unknown; **source** id (`github`, `maven`, `npm`, `pypi`, `docker`); **artifact** identifier (backticks); **version** (backticks); **contributors** (stored as the `publisher` field: comma-separated plain text, or **—** when unknown); release **date** (UTC calendar date); and a markdown **link** to the canonical URL. The project name is **not** repeated on the bullet line because it is already the `<summary>` label.

- **Release rows (HTML):** Each release is an `<li class="release">` inside the project’s `<ul>`. A single **meta** row (pipe-separated spans) carries the same fields in order: **GitHub** repo (monospace) or em dash; **source**; **artifact**; **version**; **contributors** (same `publisher` field as Markdown; escaped plain text, or em dash when unknown); **date** (UTC calendar); and a visible **“link”** anchor to the canonical URL (`href` attribute escaped for HTML). Optional **description** appears below as a `<p class="description">`: content is escaped, newlines become `<br>`, and **`white-space: pre-wrap`** preserves layout where useful.

- **Project label:** Use the landscape card **`name`** when the release resolves to that card via repo URLs or registered asset keys—including **`docker_hub`**, **`npmjs`**, and **`pypi`** (often under **`extra`**) alongside **`npm`**, **`docker`**, and other indexed fields (see *Landscape mapping*). **Maven-only:** cards may declare **`maven_groupid`** in `landscape.yml` (string or list of strings). For Maven Central rows, when the coordinate’s **`groupId`** equals that value or starts with **`maven_groupid` + `"."`** (nested group IDs such as `org.finos.vuu.plugin` under `org.finos.vuu`), the release is labeled with that card’s **`name`**. If several prefixes match, the **longest** prefix wins. If nothing matches, resolution may use GitHub org repo association or, as a last resort, a title-cased artifact/repo slug. Labels such as **`Unknown`** still produce their own collapsible section when needed.

- **Optional description (Markdown):** When normalized descriptive text is available from the upstream source, the generator emits a **second line** immediately under that bullet, indented and prefixed with `Description:` followed by the excerpt.

- **Optional description (HTML):** When a description exists, it is appended under the meta row as described above; if not, the list item contains only the meta row.

- **Description provenance by source:**
  - **GitHub:** release `body` text.
  - **Maven:** the `<description>` element from the POM at Maven Central for the released artifact version.
  - **npm:** the `description` field from the registry JSON for the specific package **version** (not only the latest package metadata).
  - **PyPI:** `info.summary` if non-empty, otherwise `info.description`.
  - **Docker Hub:** repository `full_description` if non-empty, otherwise `description`.

- **Contributors (same row as version and date; field name `publisher` in code):** a comma-separated list of human-oriented labels when the registry exposes more than one person or role. Each label uses **Display name (handle)** when both a readable name and a handle exist and differ (case-insensitive equality collapses to a single label); otherwise one value. **—** when nothing is available. **Maven** and **npm** may join several names; duplicates are dropped case-insensitively while preserving first-seen order. Provenance by source:
  - **GitHub:** release **`author`** only (one person): GitHub **`name`** (if set) and **`login`** as handle. This is the **release publisher**, not every commit author on the tag.
  - **Maven:** every **`<developer>`** under **`<developers>`** on the **released artifact’s POM** on Maven Central, then the same on each **`<parent>`** POM up the chain (same `repo1.maven.org` layout as the artifact POM), stopping at missing coordinates, fetch errors, unresolved `${…}` parent versions, or a **maximum depth** (six parents). Each developer contributes **`<name>`** or, if absent, **`<id>`**.
  - **npm:** **`maintainers`** on the version object (each **`name`**, npm username), then **`_npmUser.name`** if not already listed (tarball uploader).
  - **PyPI:** **`info.author`** and **`info.maintainer`**, split on commas, trimmed, deduplicated (package-level metadata, not necessarily the file uploader).
  - **Docker Hub:** per-tag **`last_updater_username`** only (last image pusher for that tag, not a project contributor list).

- **Normalization:** descriptions are plain text **before** HTML escaping or Markdown emission. Markup is lightly stripped (including fenced code regions, backticks, and markdown links reduced to visible label text), whitespace is collapsed, and the stored excerpt length is capped at **300 Unicode characters**. Text beyond that limit is reduced using leading complete sentences when they fit; otherwise the excerpt ends at a word boundary with a trailing ellipsis (`…`). If no non-empty description remains after normalization, the release item has **only** the primary row (Markdown bullet line, or HTML meta row without a description paragraph).

## Landscape mapping

A FINOS project may contain multiple repositories and released artifacts; use  
`https://github.com/finos/finos-landscape/blob/main/landscape.yml` as the main source of project-to-repo and project-to-asset assignment (including nested `item.repo_url`, `additional_repos`, and asset lists on the card).

Many FINOS cards use a **null `item:` key** and place **`repo_url`**, **`additional_repos`**, and **`homepage_url`** (when it points at GitHub) as **siblings of `item`** on the same mapping. The crawler treats both that outer mapping and any nested `item` dict as sources for repo URLs so the landscape **`name`** on that card maps to every listed GitHub repo (for example **Rune** and `rune-dsl`). The same outer vs nested **`item`** surfaces are scanned for **`maven_groupid`** so Maven coordinates can resolve to the card even when no asset string or repo slug match exists.

**Per-card asset lists (including under `extra`):** the indexer reads string or list-of-string values from these keys wherever they appear on the card surface (outer mapping, nested `item`, or `extra`):

| Key | Used to match |
|-----|----------------|
| **`docker_hub`** | Docker Hub releases: image coordinates (for example `finos/calm-hub` or the spaced form `finos calm-hub` from upstream), normalized the same way as legacy **`docker`** asset entries. |
| **`npmjs`** | npm registry releases: package names (for example `@finos/calm-cli`), same lookup behavior as **`npm`** when that key is present instead. Upstream may list scoped packages as **`finos/pkg`** (one slash, no `@`); those are normalized to **`@finos/pkg`** and the unscoped **`pkg`** tail for registry matching. |
| **`pypi`** | PyPI releases: **project** names as published on PyPI (the slug used in `/project/<name>/` and in crawl metadata), same as legacy **`pypi`** on the card root. |

Legacy keys **`docker`** and **`npm`** are still indexed if present. Values are deduplicated per card, expanded where needed (for example Docker Hub `finos <image>` → `finos/<image>` and short names), and registered in the same **`asset_to_project`** map used when resolving releases from Docker Hub, npm, PyPI, and other sources.

**YAML robustness:** before parsing, the loader applies a **narrow text fix** only on lines that contain **`docker_hub:`**, **`[`**, and **`]`**: it inserts missing commas between adjacent double-quoted tokens (`"a" "b"` → `"a", "b"`). That matches a recurring upstream typo in flow-style **`docker_hub`** lists and does not run on block-style lists. Invalid YAML for other reasons still fails at parse time; unit tests use handcrafted documents and do **not** continuously fetch the live **`landscape.yml`**, so regressions in the remote file are not caught unless you add a separate smoke check or fixture snapshot.

Top-level landscape entries use **`category:`** as a **null marker** with **`name`** and **`subcategories`** as sibling keys; the walker must **not** recurse into that null value (it would skip the whole subtree). **Resolution:** once a release resolves to a GitHub org repo slug (`finos/…`), the project label prefers the landscape **`repo_to_project`** entry for that slug over title-cased fallbacks (and over **`maven_groupid`**-derived labels when both apply) so the reported name matches the card **`name`** that lists the repository.

## Quality and tooling

- The code is unit tested, with **90%+** test coverage.
- There is a **dry run** execution, runnable locally with uv.
- **`latest_weekly_file(output_dir)`** (library helper): returns the newest week report path under `output_dir` by choosing the **highest numeric year** subdirectory, then the **highest numeric week** stem among **`*.html`** and **`*.md`**. If both `WW.html` and `WW.md` exist for the same week, **`.html`** is preferred.
- **`write_releases_index(output_dir)`** (library helper): calls **`write_calendar_month_pages`** first (parse/merge weekly HTML as in *Index and calendar month pages*), then writes **`output_dir/index.html`** via **`collect_year_week_html_files`** / **`render_releases_index_html`**. Intended to be invoked after week files change so **`index.html`** and **`calendar-*.html`** stay aligned with **`WW.html`** on disk for years **≥ 2026**.
- **README.md** documents install, usage (including env vars), testing, and CI.

## GitHub API authentication

GitHub org repo listing and per-repo release endpoints use the REST API. **Unauthenticated** requests hit a low rate limit and may return `403 rate limit exceeded`.

- Support **`GITHUB_TOKEN`** or **`GH_TOKEN`** (same convention as the GitHub CLI). Headers for GitHub are attached **per request to `api.github.com` only**, not on the shared HTTP client defaults: **`Accept: application/vnd.github+json`** is always sent on those requests; **`Authorization: Bearer <token>`** is added when a token is set. Crawls against npm, Maven, PyPI, Docker Hub, and the landscape YAML URL therefore **never** receive GitHub `Accept` / `Authorization` headers (avoiding registry errors such as HTTP **406** from npm when a GitHub-only `Accept` would be forwarded).
- **GitHub Actions** injects **`GITHUB_TOKEN`** automatically for the job (no extra secret required for typical public-org reads).