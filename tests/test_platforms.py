# tests/test_platforms.py
from datetime import datetime, timezone

from xbrain.models import Author, Item
from xbrain.platforms import (
    PLATFORMS,
    corpus_platform_label,
    is_hydrated,
    platform_for_item_id,
    platform_for_source,
)


def _item(item_id: str, source: str, **overrides) -> Item:
    defaults = dict(
        id=item_id,
        source=source,
        url=f"https://example.com/{item_id}",
        author=Author(handle="foo", name="Foo"),
        text="hello",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Item(**defaults)


def test_x_platform_has_empty_id_prefix_and_original_auth_filename():
    """The two invariants that keep every existing store key and auth path
    untouched — see docs/FORK.md and xbrain.platforms module docstring."""
    x = PLATFORMS["x"]
    assert x.id_prefix == ""
    assert x.auth_filename == "storage_state.json"


def test_platform_for_source_covers_all_sources():
    assert platform_for_source("bookmark").name == "x"
    assert platform_for_source("own_tweet").name == "x"
    assert platform_for_source("li_saved").name == "linkedin"


def test_platform_for_item_id_is_a_pure_prefix_test():
    assert platform_for_item_id("1619092116248084485").name == "x"
    assert platform_for_item_id("li-7123456789012345678").name == "linkedin"


def test_corpus_platform_label_x_only():
    items = [_item("1", "bookmark")]
    assert corpus_platform_label(items) == "X"


def test_corpus_platform_label_mixed():
    items = [_item("1", "bookmark"), _item("li-2", "li_saved")]
    assert corpus_platform_label(items) == "X and LinkedIn"


def test_corpus_platform_label_accepts_a_dicts_values_view():
    """The common real call shape: `corpus_platform_label(store.values())`."""
    store = {"1": _item("1", "bookmark")}
    assert corpus_platform_label(store.values()) == "X"


def test_corpus_platform_label_empty_is_x():
    assert corpus_platform_label([]) == "X"


def test_is_hydrated_false_for_a_bare_stub():
    stub = _item("li-1", "li_saved")
    assert is_hydrated(stub) is False


def test_is_hydrated_true_once_links_or_media_are_present():
    from xbrain.models import Link

    hydrated = _item("li-1", "li_saved", links=[Link(url="https://x.example", domain="x.example")])
    assert is_hydrated(hydrated) is True
