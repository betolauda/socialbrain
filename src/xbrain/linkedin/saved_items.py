"""Import LinkedIn saved posts from the official data export into Item stubs.

The export ZIP contains ``Saved_Items_<memberid>.csv``::

    savedItem,CreatedTime
    https://www.linkedin.com/feed/update/urn:li:activity:7495649402552913920,2026-08-19 01:25:29

``CreatedTime`` is the **save** date, not the post date — so ``created_at``
is decoded from the activity URN's embedded snowflake timestamp where
possible (`xbrain.linkedin.urn.post_timestamp`), falling back to
``CreatedTime`` for ``article`` URNs and any implausible decode.

Only the ``Saved_Items*.csv`` member is ever read out of the ZIP. The same
export also contains ``messages.csv``, ``Connections.csv``,
``PhoneNumbers.csv`` and ``Email Addresses.csv``; none of them may ever be
written to disk. This mirrors `xbrain.archive`: ``archive.read(member)``
into memory, nothing extracted.

Each row becomes a deliberately empty ``li_saved`` stub `Item` — no links,
no media, no enrichment — so `xbrain.platforms.is_hydrated` reports it as
not hydrated and `fetch` / `generate` correctly ignore it until a later
hydration step fills it in.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path

from xbrain.linkedin.urn import item_id, parse_saved_item, post_timestamp
from xbrain.models import Author, Item

logger = logging.getLogger(__name__)

# The saved-items member may sit at any depth in the export ZIP; match its
# basename case-insensitively.
_SAVED_ITEMS_PATTERN = "saved_items*.csv"

# `CreatedTime` column format: `YYYY-MM-DD HH:MM:SS`, no timezone marker.
# The rest of the pipeline uses timezone-aware UTC datetimes
# (`xbrain.extract.graphql._parse_x_date`, `xbrain.archive`), so the naive
# value is pinned to UTC.
_CREATED_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_saved_items(path: Path) -> list[Item]:
    """Parse a LinkedIn data export into ``li_saved`` stub items.

    ``path`` may be the export ``.zip`` or an already-extracted
    ``Saved_Items*.csv``. Items are de-duplicated by minted id (first
    occurrence wins). A malformed row is logged and skipped — never raised.
    """
    raw = _read_saved_items_csv(path)
    captured_at = datetime.now(timezone.utc)
    items: list[Item] = []
    seen: set[str] = set()
    for row in csv.DictReader(io.StringIO(raw)):
        item = _row_to_item(row, captured_at)
        if item is None or item.id in seen:
            continue
        seen.add(item.id)
        items.append(item)
    return items


def _read_saved_items_csv(path: Path) -> str:
    """Return the Saved_Items CSV text, read straight out of a ZIP if given one.

    Mirrors `xbrain.archive`: the member is ``archive.read``-ed into memory,
    never extracted — the export ZIP also holds ``messages.csv``,
    ``Connections.csv`` and other private members that must never touch disk.
    """
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            member = _find_saved_items_member(archive)
            return archive.read(member).decode("utf-8")
    return path.read_text(encoding="utf-8")


def _find_saved_items_member(archive: zipfile.ZipFile) -> str:
    """Locate the ``Saved_Items*.csv`` member at any depth, case-insensitively.

    Mirrors `xbrain.archive._find_tweets_file`: raises a clear error naming
    what was looked for (and what is present) when it is absent.
    """
    for name in archive.namelist():
        basename = name.rsplit("/", 1)[-1]
        if fnmatch(basename.lower(), _SAVED_ITEMS_PATTERN):
            return name
    raise ValueError(
        f"No saved-items file in export (looked for a '{_SAVED_ITEMS_PATTERN}' "
        f"basename at any depth); ZIP members: {sorted(archive.namelist())}"
    )


def _row_to_item(row: dict[str, str | None], captured_at: datetime) -> Item | None:
    """Map one CSV row into an ``li_saved`` stub Item, or ``None`` if malformed."""
    url = (row.get("savedItem") or "").strip()
    if not url:
        logger.warning("saved-items row has no savedItem URL, skipping: %r", row)
        return None
    parsed = parse_saved_item(url)
    if parsed is None:
        logger.warning("saved-items row has an unparseable URL, skipping: %r", url)
        return None
    kind, urn_id = parsed
    created_at = post_timestamp(kind, urn_id) or _parse_created_time(row.get("CreatedTime"))
    if created_at is None:
        logger.warning("saved-items row %r has no usable timestamp, skipping", url)
        return None
    return Item(
        id=item_id(urn_id),
        source="li_saved",
        url=url,
        author=Author(handle="", name=""),
        text="",
        created_at=created_at,
        captured_at=captured_at,
    )


def _parse_created_time(value: str | None) -> datetime | None:
    """Parse the ``CreatedTime`` column into a timezone-aware UTC datetime."""
    if not value:
        return None
    try:
        naive = datetime.strptime(value.strip(), _CREATED_TIME_FORMAT)
    except ValueError:
        logger.warning("unparseable CreatedTime %r", value)
        return None
    return naive.replace(tzinfo=timezone.utc)
