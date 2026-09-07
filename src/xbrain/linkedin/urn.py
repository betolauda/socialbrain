"""LinkedIn URN parsing, item-id minting, and post-timestamp decoding.

A LinkedIn saved-item URL from the official data export looks like::

    https://www.linkedin.com/feed/update/urn:li:activity:7495649402552913920
    https://www.linkedin.com/feed/update/urn:li:article:7215433500339197848

The embedded ``urn:li:<kind>:<digits>`` token is the stable identity. For
``activity`` URNs the digits are a snowflake — the post's publication time
lives in the high bits (``epoch_ms = int(urn_id) >> 22``), so an accurate
``created_at`` is available with zero network calls. ``article`` URNs do
*not* carry a usable timestamp this way.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from xbrain.platforms import PLATFORMS

# A saved-item URL embeds `urn:li:activity:<digits>` or `urn:li:article:<digits>`.
# Both kinds are known to appear in a real export (749 activity + 2 article on
# the measured 751-row file); both must parse and neither may crash.
_URN_RE = re.compile(r"urn:li:(?P<kind>activity|article):(?P<id>\d+)")

# LinkedIn was founded in 2003 — a decoded activity timestamp earlier than
# this (or in the future) means the snowflake trick did not apply to this id
# and the caller must fall back to the export's `CreatedTime` column.
_LINKEDIN_EPOCH = datetime(2003, 1, 1, tzinfo=timezone.utc)

# Kind, then digits — a parsed saved-item URN.
ParsedUrn = tuple[str, str]


def parse_saved_item(value: str) -> ParsedUrn | None:
    """Parse a saved-item URL (or bare URN) into ``(kind, urn_id)``.

    Returns ``None`` for anything without a recognisable
    ``urn:li:activity:<digits>`` / ``urn:li:article:<digits>`` token.
    """
    if not value:
        return None
    match = _URN_RE.search(value)
    if match is None:
        return None
    return match.group("kind"), match.group("id")


def item_id(urn_id: str) -> str:
    """Mint the store item id for a LinkedIn saved post.

    ``<id_prefix><urn_id>``, where the prefix is read from the platform
    registry (``"li-"``) rather than hardcoded, so
    ``xbrain.platforms.platform_for_item_id`` round-trips the id back to the
    LinkedIn platform.
    """
    return f"{PLATFORMS['linkedin'].id_prefix}{urn_id}"


def post_timestamp(kind: str, urn_id: str) -> datetime | None:
    """Decode the post's publication time from an ``activity`` URN id.

    ``epoch_ms = int(urn_id) >> 22`` — the same high-bits-are-a-timestamp
    trick as a snowflake id. Returns a timezone-aware UTC datetime, or
    ``None`` when the trick does not apply:

    - ``kind`` is not ``"activity"`` (an ``article`` id decodes to a
      nonsense date roughly 7 years off).
    - the decoded datetime is implausible: before LinkedIn existed (2003)
      or in the future relative to now.

    In every ``None`` case the caller falls back to the export's
    ``CreatedTime`` column.
    """
    if kind != "activity":
        return None
    try:
        epoch_ms = int(urn_id) >> 22
    except ValueError:
        return None
    try:
        decoded = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None
    if decoded < _LINKEDIN_EPOCH or decoded > datetime.now(timezone.utc):
        return None
    return decoded
