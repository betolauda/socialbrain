# tests/test_cursors.py
from datetime import datetime, timezone

from xbrain.cursors import newest_id
from xbrain.models import Author, Item


def _item(item_id: str, created_at: datetime) -> Item:
    return Item(
        id=item_id,
        source="bookmark",
        url=f"https://example.com/{item_id}",
        author=Author(handle="foo", name="Foo"),
        text="hello",
        created_at=created_at,
        captured_at=created_at,
    )


def test_newest_id_empty_list_is_none():
    assert newest_id([]) is None


def test_newest_id_all_numeric_orders_by_int_value():
    """Reproduces upstream's exact prior `int(i.id)` behaviour for X ids —
    numeric string order would get "9" > "10" wrong; int order must not."""
    items = [
        _item("9", datetime(2026, 1, 3, tzinfo=timezone.utc)),
        _item("10", datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ]
    assert newest_id(items) == "10"


def test_newest_id_falls_back_to_created_at_for_non_numeric_ids():
    """A LinkedIn-shaped id (`li-<digits>`) would raise under `int()` —
    this must degrade to chronological order instead of crashing."""
    items = [
        _item("li-1", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        _item("li-2", datetime(2026, 1, 5, tzinfo=timezone.utc)),
    ]
    assert newest_id(items) == "li-2"


def test_newest_id_mixed_numeric_and_namespaced_uses_date_order():
    items = [
        _item("999999999999999999", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        _item("li-1", datetime(2026, 1, 5, tzinfo=timezone.utc)),
    ]
    assert newest_id(items) == "li-1"


def test_newest_id_tiebreaks_on_id_when_dates_are_equal():
    same_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items = [_item("li-a", same_date), _item("li-b", same_date)]
    assert newest_id(items) == "li-b"
