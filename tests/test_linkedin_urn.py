"""Tests for `xbrain.linkedin.urn` — URN parsing, id minting, timestamp decode."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from xbrain.linkedin.urn import item_id, parse_saved_item, post_timestamp
from xbrain.platforms import platform_for_item_id


def _activity_urn_id(dt: datetime) -> str:
    """Mint an `activity` URN id whose high bits encode `dt` exactly.

    The low 22 bits are zeroed, so `int(urn_id) >> 22` recovers `epoch_ms`
    with no truncation loss — the decode round-trips to `dt` to the ms.
    """
    epoch_ms = int(dt.timestamp() * 1000)
    return str(epoch_ms << 22)


def test_parse_activity_url() -> None:
    parsed = parse_saved_item(
        "https://www.linkedin.com/feed/update/urn:li:activity:7495649402552913920"
    )
    assert parsed == ("activity", "7495649402552913920")


def test_parse_article_url() -> None:
    parsed = parse_saved_item(
        "https://www.linkedin.com/feed/update/urn:li:article:7215433500339197848"
    )
    assert parsed == ("article", "7215433500339197848")


def test_parse_returns_none_for_unparseable() -> None:
    assert parse_saved_item("https://example.com/not-a-linkedin-url") is None
    assert parse_saved_item("") is None
    assert parse_saved_item("urn:li:company:1234") is None


def test_item_id_uses_registry_prefix_and_round_trips() -> None:
    minted = item_id("7495649402552913920")
    assert minted == "li-7495649402552913920"
    # `platform_for_item_id` must resolve the minted id back to LinkedIn.
    assert platform_for_item_id(minted).name == "linkedin"


def test_post_timestamp_decodes_activity_to_known_value() -> None:
    known = datetime(2024, 6, 15, 9, 30, 0, tzinfo=timezone.utc)
    decoded = post_timestamp("activity", _activity_urn_id(known))
    assert decoded == known


def test_post_timestamp_rejects_garbage_id() -> None:
    # `123 >> 22 == 0` -> epoch 1970 -> before LinkedIn existed -> None.
    assert post_timestamp("activity", "123") is None


def test_post_timestamp_rejects_future_decode() -> None:
    future = datetime.now(timezone.utc) + timedelta(days=3650)
    assert post_timestamp("activity", _activity_urn_id(future)) is None


def test_post_timestamp_none_for_article_kind() -> None:
    # A real article id — decoding it as a snowflake gives a nonsense date,
    # so the function must not even try for a non-activity kind.
    assert post_timestamp("article", "7215433500339197848") is None


def test_post_timestamp_non_numeric_id() -> None:
    assert post_timestamp("activity", "not-a-number") is None
