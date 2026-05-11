from weekly_releases.models import format_publisher_label


def test_format_publisher_label_name_and_handle():
    assert format_publisher_label("Ada Lovelace", "alovelace") == "Ada Lovelace (alovelace)"


def test_format_publisher_label_handle_only():
    assert format_publisher_label(None, "finos-admin") == "finos-admin"


def test_format_publisher_label_name_only():
    assert format_publisher_label("FINOS", None) == "FINOS"


def test_format_publisher_label_collapses_duplicate_name_handle():
    assert format_publisher_label("octocat", "octocat") == "octocat"
    assert format_publisher_label("OctoCat", "octocat") == "OctoCat"


def test_format_publisher_label_empty():
    assert format_publisher_label(None, None) is None
    assert format_publisher_label("", "  ") is None
