from weekly_releases.description_text import (
    MAX_DESCRIPTION_LENGTH,
    normalize_release_description,
)


def test_normalize_returns_none_for_empty():
    assert normalize_release_description(None) is None
    assert normalize_release_description("") is None
    assert normalize_release_description("   ") is None


def test_normalize_strips_fenced_code():
    raw = "Intro.\n```java\nvoid x();\n```\nMore text."
    out = normalize_release_description(raw)
    assert out is not None
    assert "```" not in out
    assert "void" in out or "Intro" in out


def test_normalize_respects_short_input():
    assert normalize_release_description("Hello world.") == "Hello world."


def test_normalize_truncates_long_text_to_budget():
    raw = " ".join(f"Sentence number {i}." for i in range(80))
    out = normalize_release_description(raw)
    assert out is not None
    assert len(out) <= MAX_DESCRIPTION_LENGTH
    assert out.endswith("…")


def test_normalize_keeps_multiple_short_sentences_under_limit():
    raw = "First. Second. Third."
    out = normalize_release_description(raw)
    assert out == raw


def test_normalize_truncates_single_sentence_without_spaces():
    raw = "x" * 400
    out = normalize_release_description(raw)
    assert out is not None
    assert len(out) <= MAX_DESCRIPTION_LENGTH
    assert out.endswith("…")


def test_normalize_github_release_style_heading_stripped():
    raw = "## What's changed\n\n- fix a\n- fix b"
    out = normalize_release_description(raw)
    assert out is not None
    assert "##" not in out
