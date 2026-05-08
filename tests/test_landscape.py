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

