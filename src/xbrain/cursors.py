"""Cursor-advance ordering policy for the extractor.

Fork addition (see `docs/FORK.md`). Upstream's `cli._run_extract` advanced
the incremental cursor with ``max(items, key=lambda i: int(i.id)).id`` — a
correct and exact ordering for X, whose ids are monotonic snowflakes, but
one that raises `ValueError` on a LinkedIn item id (`li-<digits>`, an
opaque namespaced string, not a snowflake).
"""

from __future__ import annotations

import re

from xbrain.models import Item

_NUMERIC_ID = re.compile(r"[0-9]+")


def newest_id(items: list[Item]) -> str | None:
    """The id of the newest item in a freshly-extracted batch.

    When every id in the batch is purely numeric (the X case: snowflake
    ids are monotonic, so `int(id)` order IS true capture order — this
    branch reproduces upstream's exact prior behaviour), order by that.
    Otherwise (any namespaced id, e.g. LinkedIn's `li-<digits>`) fall back
    to `(created_at, id)` — chronological, with the id as a deterministic
    tiebreak so the result never depends on input ordering.
    """
    if not items:
        return None
    if all(_NUMERIC_ID.fullmatch(item.id) for item in items):
        return max(items, key=lambda item: int(item.id)).id
    return max(items, key=lambda item: (item.created_at, item.id)).id
