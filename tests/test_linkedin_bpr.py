"""Tests for `xbrain.linkedin.bpr` — parsing BigPipe Voyager payloads out of HTML.

Every fixture is constructed inline from the *shape* recorded during
reconnaissance (docs/LINKEDIN_HYDRATE.md) — never copied from `linkedin_data/`,
which holds real third-party data.
"""

from __future__ import annotations

import html
import json

from xbrain.linkedin import bpr

_UPDATE_URN = "urn:li:fsd_update:(urn:li:activity:111,FEED_DETAIL,EMPTY,DEFAULT,false)"


def _update_entity() -> dict:
    return {
        "entityUrn": _UPDATE_URN,
        "$type": "com.linkedin.voyager.dash.feed.Update",
        "content": {},
        "commentary": None,
        "actor": None,
    }


def _block(payload: object, *, guid: str = "613052", id_first: bool = False) -> str:
    """One ``<code id="bpr-guid-...">`` block wrapping an HTML-escaped JSON body."""
    body = html.escape(payload if isinstance(payload, str) else json.dumps(payload))
    if id_first:
        return f'<code id="bpr-guid-{guid}" data-a="b" style="display:none">{body}</code>'
    return f'<code style="display: none" id="bpr-guid-{guid}">{body}</code>'


def test_blocks_extracted_regardless_of_attribute_order() -> None:
    page = (
        "<html><body>"
        + _block({"included": [{"entityUrn": "urn:li:a:1"}]}, guid="1")
        + _block({"included": [{"entityUrn": "urn:li:a:2"}]}, guid="2", id_first=True)
        + "</body></html>"
    )

    pool = bpr.build_pool(page)

    assert set(pool) == {"urn:li:a:1", "urn:li:a:2"}


def test_non_json_block_is_skipped_not_raised() -> None:
    page = _block("this is not json {{{", guid="1") + _block(
        {"included": [{"entityUrn": "urn:li:a:1"}]}, guid="2"
    )

    pool = bpr.build_pool(page)

    assert set(pool) == {"urn:li:a:1"}


def test_html_entities_in_values_are_unescaped() -> None:
    page = _block({"included": [{"entityUrn": "urn:li:a:1", "note": 'A & B "quoted" <x>'}]})

    pool = bpr.build_pool(page)

    assert pool["urn:li:a:1"]["note"] == 'A & B "quoted" <x>'


def test_included_arrays_merge_across_blocks() -> None:
    page = _block({"included": [{"entityUrn": "urn:li:a:1", "v": 1}]}, guid="1") + _block(
        {"included": [{"entityUrn": "urn:li:a:2", "v": 2}]}, guid="2"
    )

    pool = bpr.build_pool(page)

    assert pool["urn:li:a:1"]["v"] == 1
    assert pool["urn:li:a:2"]["v"] == 2


def test_deref_resolves_star_reference_against_pool() -> None:
    referenced = {"entityUrn": "urn:li:digitalmediaAsset:X", "duration": 5000}
    page = _block({"included": [_update_entity(), referenced]})

    parsed = bpr.find_update(page)

    assert parsed is not None
    assert parsed.deref("urn:li:digitalmediaAsset:X") == referenced
    assert parsed.deref(None) is None
    assert parsed.deref("urn:li:missing") is None


def test_find_update_returns_none_when_no_update_present() -> None:
    page = _block({"included": [{"entityUrn": "urn:li:a:1", "$type": "something.Else"}]})

    assert bpr.find_update(page) is None


def test_find_update_returns_the_update_entity_and_pool() -> None:
    page = (
        "<div>" + _block({"included": [_update_entity(), {"entityUrn": "urn:li:a:9"}]}) + "</div>"
    )

    parsed = bpr.find_update(page)

    assert parsed is not None
    assert parsed.update["entityUrn"] == _UPDATE_URN
    assert "urn:li:a:9" in parsed.pool
