"""Parse LinkedIn's BigPipe-rendered (BPR) Voyager payloads out of a post page.

A LinkedIn post detail page is server-side-rendered: the Voyager models that
would otherwise arrive over ``/voyager/api/`` XHRs are inlined into the initial
HTML as a sequence of ``<code style="display:none" id="bpr-guid-NNNNNN">``
blocks, each an HTML-escaped ``{data, meta, included}`` Voyager envelope.

This module is **pure** — it takes an HTML string and returns plain dicts. No
browser, no network. The hydrator (`xbrain.linkedin.hydrate`) fetches the HTML;
everything that can be wrong about the parse lives here where it is testable.

The reconnaissance capture (docs/LINKEDIN_HYDRATE.md) measured ~9 BPR blocks per
page, exactly one of which carries a
``com.linkedin.voyager.dash.feed.Update`` entity in its ``included`` array.
Merging every block's ``included`` gives ~104 entities keyed by ``entityUrn``;
fields prefixed with ``*`` are URN references into that merged pool (standard
Voyager denormalisation).
"""

from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_UPDATE_TYPE = "com.linkedin.voyager.dash.feed.Update"

# Match a BPR block on its ``id="bpr-guid-<digits>"`` attribute, tolerant of
# attribute order (``style`` may precede or follow ``id``) and of the exact
# ``style`` value LinkedIn uses to hide the block. ``[^>]*`` stays within the
# opening tag; ``re.DOTALL`` lets the body span newlines.
_BPR_BLOCK_RE = re.compile(
    r'<code\b[^>]*\bid="bpr-guid-\d+"[^>]*>(.*?)</code>',
    re.DOTALL,
)


@dataclass(frozen=True)
class ParsedPage:
    """A parsed post page: the ``Update`` entity plus the merged entity pool.

    ``pool`` is every BPR block's ``included`` entities merged into one dict
    keyed by ``entityUrn`` — the target of every ``*``-prefixed reference field
    on ``update`` (and, transitively, on the entities it points at).
    """

    update: dict
    pool: dict[str, dict]

    def deref(self, ref: str | None) -> dict | None:
        """Resolve a ``*``-reference URN against the pool.

        ``ref`` is the raw value of a ``*``-prefixed field (e.g.
        ``update["content"]["linkedInVideoComponent"]["*videoPlayMetadata"]``).
        Returns the referenced entity, or ``None`` when ``ref`` is falsy or
        absent from the pool.
        """
        if not ref:
            return None
        return self.pool.get(ref)


def _iter_bpr_payloads(page_html: str) -> Iterator[dict]:
    """Yield the decoded JSON object of every BPR block; skip anything unparseable.

    A block whose body is not valid JSON (or not a JSON object) is logged at
    debug level and skipped — never raised. LinkedIn ships a few non-Voyager
    blocks (feature flags, tracking) that are not our concern.
    """
    for match in _BPR_BLOCK_RE.finditer(page_html):
        raw = html.unescape(match.group(1))
        try:
            payload = json.loads(raw)
        except ValueError:
            logger.debug("skipping non-JSON BPR block")
            continue
        if isinstance(payload, dict):
            yield payload


def build_pool(page_html: str) -> dict[str, dict]:
    """Merge every BPR block's ``included`` array into one ``entityUrn``-keyed dict.

    Later blocks win on a duplicate ``entityUrn`` (they are typically the more
    complete copy). Entities without an ``entityUrn`` are skipped — they cannot
    be referenced.
    """
    pool: dict[str, dict] = {}
    for payload in _iter_bpr_payloads(page_html):
        included = payload.get("included")
        if not isinstance(included, list):
            continue
        for entity in included:
            if not isinstance(entity, dict):
                continue
            urn = entity.get("entityUrn")
            if isinstance(urn, str):
                pool[urn] = entity
    return pool


def _find_update_entity(pool: dict[str, dict]) -> dict | None:
    """Return the single ``Update`` entity in the pool, or ``None``."""
    for entity in pool.values():
        if entity.get("$type") == _UPDATE_TYPE:
            return entity
    return None


def find_update(page_html: str) -> ParsedPage | None:
    """Parse a post page into a `ParsedPage`, or ``None`` when it carries no Update.

    ``None`` means the page had no ``com.linkedin.voyager.dash.feed.Update``
    entity at all — a deleted post, an interstitial, or a page shape we do not
    recognise. The hydrator records that as a ``not_found`` failure.
    """
    pool = build_pool(page_html)
    update = _find_update_entity(pool)
    if update is None:
        return None
    return ParsedPage(update=update, pool=pool)
