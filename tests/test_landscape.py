from weekly_releases.landscape import parse_landscape


def test_parse_landscape_maps_repos_and_assets():
    raw = """
landscape:
  items:
    - name: Project A
      repo_url: https://github.com/finos/project-a
      npm:
        - "@finos/a"
      maven: project-a-core
    - name: Group
      items:
        - name: Project B
          repo_url: https://github.com/finos/project-b
          docker: project-b
"""
    index = parse_landscape(raw)
    assert index.project_for_repo("project-a") == "Project A"
    assert index.project_for_repo("project-b") == "Project B"
    assert index.project_for_asset("@finos/a") == "Project A"
    assert index.project_for_asset("project-b") == "Project B"
    assert index.project_for_asset("unknown") == "Unknown"


def test_parse_landscape_with_top_level_list():
    raw = """
landscape:
  - name: Project C
    repo_url: https://github.com/finos/project-c
    npm:
      - "@finos/c"
"""
    index = parse_landscape(raw)
    assert index.project_for_repo("project-c") == "Project C"
    assert index.project_for_asset("@finos/c") == "Project C"


def test_parse_landscape_null_category_key_like_upstream_fin_os_yaml():
    """``category:`` with null must not short-circuit the walker (real ``landscape.yml`` shape)."""
    raw = """
landscape:
  - category:
    name: Data
    subcategories:
      - subcategory:
        name: Frameworks
        items:
          - name: Rune
            item:
            homepage_url: https://github.com/finos/rune-dsl
"""
    index = parse_landscape(raw)
    assert index.project_for_repo("rune-dsl") == "Rune"


def test_parse_landscape_finos_flat_item_sibling_repos_like_upstream_yaml():
    """Matches FINOS cards where ``item:`` is null and repos live beside ``item``."""
    raw = """
landscape:
  items:
    - license: Apache License 2.0
      logo: rune.svg
      name: Rune
      item:
      project: incubating
      homepage_url: https://github.com/finos/rune-dsl
      additional_repos:
        - repo_url: https://github.com/finos/rune-dsl
        - repo_url: https://github.com/finos/rune-testing
"""
    index = parse_landscape(raw)
    assert index.project_for_repo("rune-dsl") == "Rune"
    assert index.project_for_repo("rune-testing") == "Rune"


def test_nested_repo_cards_use_parent_program_name():
    raw = """
landscape:
  items:
    - name: Morphir
      item:
        repo_url: https://github.com/finos/morphir
      items:
        - name: Morphir Go
          item:
            repo_url: https://github.com/finos/morphir-go
    - name: Rune
      item:
        repo_url: https://github.com/finos/rune-dsl
      items:
        - name: Rune Python Generator
          item:
            repo_url: https://github.com/finos/rune-python-generator
"""
    index = parse_landscape(raw)
    assert index.project_for_repo("morphir") == "Morphir"
    assert index.project_for_repo("morphir-go") == "Morphir"
    assert index.project_for_repo("rune-dsl") == "Rune"
    assert index.project_for_repo("rune-python-generator") == "Rune"


def test_parse_landscape_reads_nested_item_and_docker_hub():
    raw = """
landscape:
  items:
    - name: Legend
      item:
        repo_url: https://github.com/finos/legend
        additional_repos:
          - repo_url: https://github.com/finos/legend-studio
        docker_hub:
          - "finos legend-studio"
"""
    index = parse_landscape(raw)
    assert index.project_for_repo("legend") == "Legend"
    assert index.project_for_repo("legend-studio") == "Legend"
    assert index.project_for_asset("finos/legend-studio") == "Legend"
    assert index.repo_for_asset("legend-studio") == "legend-studio"


def test_parse_landscape_repairs_missing_commas_in_docker_hub_flow_sequence():
    """Upstream finos-landscape has shipped a one-line ``docker_hub: [ "a" "b" ]`` typo (no comma)."""
    raw = """
landscape:
  items:
    - name: Legend
      item:
        repo_url: https://github.com/finos/legend
      extra:
        docker_hub: ["finos legend-engine-pure-ide-light-http-server" "finos legend-engine-server-http-server"]
"""
    index = parse_landscape(raw)
    assert index.project_for_repo("legend") == "Legend"
    assert (
        index.project_for_asset("finos/legend-engine-pure-ide-light-http-server")
        == "Legend"
    )
    assert (
        index.project_for_asset("finos/legend-engine-server-http-server") == "Legend"
    )


def test_parse_landscape_npmjs_finos_slash_form_maps_at_finos_packages():
    """``npmjs: [finos/calm-cli]`` (upstream style) must match crawl artifact ``@finos/calm-cli``."""
    raw = """
landscape:
  items:
    - name: CALM
      item:
      repo_url: https://github.com/finos/calm
      extra:
        npmjs: ["finos/calm-cli"]
"""
    index = parse_landscape(raw)
    assert index.project_for_asset("@finos/calm-cli") == "CALM"
    assert index.project_for_asset("calm-cli") == "CALM"
    assert index.project_for_asset("finos/calm-cli") == "CALM"


def test_parse_landscape_extra_docker_hub_npmjs_pypi():
    """FINOS cards often list produced artifacts only under ``extra``."""
    raw = """
landscape:
  items:
    - name: CALM
      item:
      repo_url: https://github.com/finos/calm
      extra:
        docker_hub:
          - finos/calm-hub
        npmjs:
          - "@finos/calm-cli"
        pypi:
          - rune_runtime
"""
    index = parse_landscape(raw)
    assert index.project_for_repo("calm") == "CALM"
    assert index.project_for_asset("finos/calm-hub") == "CALM"
    assert index.project_for_asset("@finos/calm-cli") == "CALM"
    assert index.project_for_asset("rune_runtime") == "CALM"


def test_parse_landscape_maven_groupid_maps_nested_groups():
    raw = """
landscape:
  items:
    - name: VUU
      item:
        repo_url: https://github.com/finos/vuu
      maven_groupid: "org.finos.vuu"
"""
    index = parse_landscape(raw)
    assert index.project_for_maven_group_id("org.finos.vuu") == "VUU"
    assert index.project_for_maven_group_id("org.finos.vuu.plugin") == "VUU"
    assert index.project_for_maven_group_id("org.finos.cdm") == "Unknown"


def test_parse_landscape_maven_groupid_under_extra_like_upstream_fin_os_yaml():
    """FINOS upstream places ``maven_groupid`` under ``extra`` on many cards."""
    raw = """
landscape:
  items:
    - name: VUU
      item:
      repo_url: https://github.com/finos/vuu
      extra:
        lead: example
        maven_groupid: "org.finos.vuu"
    - name: Common Domain Model
      item:
      repo_url: https://github.com/finos/common-domain-model
      extra:
        maven_groupid: "org.finos.cdm"
"""
    index = parse_landscape(raw)
    assert index.project_for_maven_group_id("org.finos.vuu") == "VUU"
    assert index.project_for_maven_group_id("org.finos.vuu.plugin") == "VUU"
    assert index.project_for_maven_group_id("org.finos.cdm") == "Common Domain Model"
    assert (
        index.project_for_maven_group_id("org.finos.cdm.foo") == "Common Domain Model"
    )


def test_project_for_maven_group_id_empty_and_whitespace_unknown():
    index = parse_landscape("""
landscape:
  items:
    - name: X
      repo_url: https://github.com/finos/x
      maven_groupid: "org.finos.x"
""")
    assert index.project_for_maven_group_id("") == "Unknown"
    assert index.project_for_maven_group_id("  ") == "Unknown"


def test_parse_landscape_maven_groupid_list_form():
    raw = """
landscape:
  items:
    - name: Multi
      repo_url: https://github.com/finos/multi
      maven_groupid:
        - "org.finos.multi.core"
        - "   "
        - "org.finos.multi"
"""
    index = parse_landscape(raw)
    assert index.project_for_maven_group_id("org.finos.multi.core.extra") == "Multi"
    assert index.project_for_maven_group_id("org.finos.multi.depot") == "Multi"


def test_project_for_maven_group_id_longest_prefix_wins():
    raw = """
landscape:
  items:
    - name: Legend
      item:
        repo_url: https://github.com/finos/legend
      maven_groupid: "org.finos.legend"
    - name: Whole Org
      item:
        repo_url: https://github.com/finos/toolbox
      maven_groupid: "org.finos"
"""
    index = parse_landscape(raw)
    assert index.project_for_maven_group_id("org.finos.legend.depot") == "Legend"
    assert index.project_for_maven_group_id("org.finos.toolbox") == "Whole Org"
