"""The source ↔ platform registry — the single seam that keeps the rest of
the core source-agnostic.

Fork addition (see `docs/FORK.md`): this file exists so that every other
core module changed for a second source needs, at most, an appended
literal or an appended default field — never a branch on a platform name.
`PLATFORMS["x"]` pins the pre-fork behaviour exactly (empty `id_prefix`,
the original `storage_state.json` filename) so every existing store key,
note filename and auth path stays byte-identical for X.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from xbrain.models import Item, SourceName

PlatformName = Literal["x", "linkedin"]


@dataclass(frozen=True)
class Platform:
    """Static, source-agnostic facts about one platform.

    `id_prefix` and `auth_filename` are the two invariants pinned by
    `tests/test_platforms.py` for `"x"` — they are what keeps every
    existing `items.json` key and `auth/storage_state.json` path unchanged.
    """

    name: PlatformName
    display: str
    sources: tuple[SourceName, ...]
    own_sources: frozenset[SourceName]
    id_prefix: str
    hosts: frozenset[str]
    auth_filename: str


PLATFORMS: dict[PlatformName, Platform] = {
    "x": Platform(
        name="x",
        display="X",
        sources=("bookmark", "own_tweet"),
        own_sources=frozenset({"own_tweet"}),
        id_prefix="",
        hosts=frozenset(
            {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}
        ),
        auth_filename="storage_state.json",
    ),
    "linkedin": Platform(
        name="linkedin",
        display="LinkedIn",
        sources=("li_saved",),
        own_sources=frozenset(),
        id_prefix="li-",
        hosts=frozenset({"linkedin.com", "www.linkedin.com"}),
        auth_filename="linkedin_storage_state.json",
    ),
}

SOURCE_PLATFORM: dict[SourceName, PlatformName] = {
    source: platform.name for platform in PLATFORMS.values() for source in platform.sources
}


def platform_for_source(source: SourceName) -> Platform:
    """The platform a given item source belongs to."""
    return PLATFORMS[SOURCE_PLATFORM[source]]


def platform_for_item_id(item_id: str) -> Platform:
    """The platform an item id belongs to, by its namespacing prefix.

    A pure string test — no store lookup needed. Every non-X platform mints
    ids with a non-empty `id_prefix` (see `xbrain.linkedin.urn.item_id`);
    X ids (numeric snowflakes or archive `id_str` values) never match a
    non-empty prefix, so they fall through to `"x"`, the empty-prefix
    platform — pinned by `tests/test_platforms.py`.
    """
    for platform in PLATFORMS.values():
        if platform.id_prefix and item_id.startswith(platform.id_prefix):
            return platform
    return PLATFORMS["x"]


def corpus_platform_label(store: dict[str, Item]) -> str:
    """A human-readable label for which platform(s) a corpus spans.

    Used by corpus-wide LLM prompts (`vocab`, `topics`) where there is no
    single item to key wording off of. Returns e.g. ``"X"``,
    ``"LinkedIn"``, or ``"X and LinkedIn"`` for a mixed corpus — ordered by
    the `PLATFORMS` registry, not alphabetically, so X (the original
    platform) always leads.
    """
    present_names = {platform_for_source(item.source).name for item in store.values()}
    labels = [p.display for p in PLATFORMS.values() if p.name in present_names]
    return " and ".join(labels) if labels else "X"


def is_hydrated(item: Item) -> bool:
    """Whether an item has real content beyond its stub fields.

    An imported-but-not-yet-hydrated LinkedIn saved post has no links, no
    media and no enrichment — see `xbrain.linkedin.saved_items` for why a
    stub is deliberately shaped that way (it is invisible to `fetch` and
    `generate` until hydration fills it in).
    """
    return bool(item.links or item.media or item.enriched)
