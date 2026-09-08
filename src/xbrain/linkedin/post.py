"""Map a parsed LinkedIn ``Update`` entity to the fields an `Item` stub needs.

This module is **pure** — dicts in, a `PostContent` out. No browser, no network.
Every field path was read off the reconnaissance capture
(`linkedin_data/recon/_shapes.json`, 7 real posts); see
docs/LINKEDIN_HYDRATE.md for the measured shape table.

The `Update` ``content`` field is a union of ~30 nullable components, at most one
non-null per post. We recognise three:

- ``imageComponent``           — 1..N images (a "carousel" is just multi-image).
- ``linkedInVideoComponent``   — a native video, its streams behind a ``*`` ref.
- ``articleComponent`` (``EXTERNAL_FULL``) — an external-link *share*, not a
  native article: no post body, no media, just a `Link`.

Anything else degrades to text-only (``is_unknown_component``) — never a raise,
so a `documentComponent` / poll / reshare we have not seen yet is safe.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

from xbrain.models import Author, Link, MediaEntry, MediaPhotoPending, MediaVideoPending

logger = logging.getLogger(__name__)

_EXTERNAL_SHARE_TYPE = "EXTERNAL_FULL"


@dataclass(frozen=True)
class PostContent:
    """Structured fields extracted from a LinkedIn post, ready to apply to an `Item`.

    - ``text``    — the post body (``""`` when the post has none, e.g. an
      external-link share, whose ``text`` instead holds the share's
      title + description).
    - ``author``  — the display name + handle, or ``None`` when the ``actor`` is
      empty (external-link shares carry no actor).
    - ``media``   — pending photo / video entries, ready for ``xbrain media`` /
      ``download-videos``.
    - ``links``   — external URLs (an external-link share's target; best-effort
      inline hyperlinks in the body).
    - ``is_external_share``   — ``True`` for an ``EXTERNAL_FULL`` article share:
      the hydrator must not expect a post body, and the existing ``fetch`` stage
      pulls the real page.
    - ``is_unknown_component`` — ``True`` when no recognised component was
      present: text-only degrade, the caller logs it.
    """

    text: str = ""
    author: Author | None = None
    media: list[MediaEntry] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    is_external_share: bool = False
    is_unknown_component: bool = False


def _text_of(node: object) -> str:
    """Return ``node["text"]`` when ``node`` is a ``{"text": str, ...}`` dict, else ``""``."""
    if isinstance(node, Mapping):
        value = node.get("text")
        if isinstance(value, str):
            return value
    return ""


def _commentary_text(update: Mapping) -> str:
    """The post body from ``update.commentary.text.text`` — ``""`` when absent."""
    commentary = update.get("commentary")
    if not isinstance(commentary, Mapping):
        return ""
    return _text_of(commentary.get("text"))


def _handle_from_profile_url(url: str) -> str:
    """Parse ``<handle>`` out of a ``https://www.linkedin.com/in/<handle>?...`` URL."""
    path = urlparse(url).path.strip("/")
    if not path.startswith("in/"):
        return ""
    return path[len("in/") :].split("/")[0]


def _author_of(update: Mapping) -> Author | None:
    """Build the `Author` from ``update.actor``; ``None`` when the actor is empty."""
    actor = update.get("actor")
    if not isinstance(actor, Mapping) or not actor:
        return None
    name = _text_of(actor.get("name"))
    nav = actor.get("navigationContext")
    target = nav.get("actionTarget", "") if isinstance(nav, Mapping) else ""
    handle = _handle_from_profile_url(target) if isinstance(target, str) else ""
    if not name and not handle:
        return None
    return Author(handle=handle, name=name)


def _vector_image_url(vector_image: Mapping) -> str | None:
    """Full URL of the largest artifact of a Voyager ``vectorImage`` node.

    ``rootUrl + fileIdentifyingUrlPathSegment`` — except a segment that is
    already an absolute URL (video thumbnails ship one, with an empty
    ``rootUrl``), which is used verbatim. Returns ``None`` on a shape mismatch.
    """
    root = vector_image.get("rootUrl")
    artifacts = vector_image.get("artifacts")
    if not isinstance(root, str) or not isinstance(artifacts, list):
        return None
    usable = [
        a
        for a in artifacts
        if isinstance(a, Mapping)
        and isinstance(a.get("width"), int)
        and isinstance(a.get("fileIdentifyingUrlPathSegment"), str)
    ]
    if not usable:
        return None
    largest = max(usable, key=lambda a: a["width"])
    segment: str = largest["fileIdentifyingUrlPathSegment"]
    if segment.startswith("http://") or segment.startswith("https://"):
        return segment
    return root + segment


def _image_vector(image: Mapping) -> Mapping | None:
    """Dig ``image.attributes[0].detailData.vectorImage`` out, guarding every hop."""
    attributes = image.get("attributes")
    if not isinstance(attributes, list) or not attributes:
        return None
    first = attributes[0]
    if not isinstance(first, Mapping):
        return None
    detail = first.get("detailData")
    if not isinstance(detail, Mapping):
        return None
    vector = detail.get("vectorImage")
    return vector if isinstance(vector, Mapping) else None


def _photos_from_image_component(component: Mapping) -> list[MediaEntry]:
    """One `MediaPhotoPending` per image in an ``imageComponent`` (largest artifact)."""
    images = component.get("images")
    if not isinstance(images, list):
        return []
    media: list[MediaEntry] = []
    for image in images:
        if not isinstance(image, Mapping):
            continue
        vector = _image_vector(image)
        if vector is None:
            continue
        url = _vector_image_url(vector)
        if url:
            media.append(MediaPhotoPending(url=url))
    return media


def _progressive_mp4s(vpm: Mapping) -> list[Mapping]:
    """The progressive-download streams of a ``VideoPlayMetadata`` entity."""
    streams = vpm.get("progressiveStreams")
    return [s for s in streams if isinstance(s, Mapping)] if isinstance(streams, list) else []


def _stream_url(stream: Mapping) -> str | None:
    """The playable URL of one progressive stream (``streamingLocations[0].url``)."""
    locations = stream.get("streamingLocations")
    if not isinstance(locations, list):
        return None
    for location in locations:
        if isinstance(location, Mapping) and isinstance(location.get("url"), str):
            return location["url"]
    return None


def _stream_bitrate(stream: Mapping) -> int | None:
    """The bitrate of one progressive stream — Voyager spells it ``bitRate``."""
    for key in ("bitRate", "bitrate"):
        value = stream.get(key)
        if isinstance(value, int):
            return value
    return None


def _hls_url(vpm: Mapping) -> str | None:
    """The HLS master-playlist URL from ``adaptiveStreams[].masterPlaylists[].url``."""
    adaptive = vpm.get("adaptiveStreams")
    if not isinstance(adaptive, list):
        return None
    for stream in adaptive:
        if not isinstance(stream, Mapping):
            continue
        playlists = stream.get("masterPlaylists")
        if not isinstance(playlists, list):
            continue
        for playlist in playlists:
            if isinstance(playlist, Mapping) and isinstance(playlist.get("url"), str):
                return playlist["url"]
    return None


def _pick_video_stream(vpm: Mapping) -> tuple[str | None, int | None]:
    """Choose the best playable stream: highest-bitrate mp4, else first mp4, else HLS."""
    candidates: list[tuple[str, int | None]] = []
    for stream in _progressive_mp4s(vpm):
        url = _stream_url(stream)
        if url:
            candidates.append((url, _stream_bitrate(stream)))
    if not candidates:
        return _hls_url(vpm), None
    best_url: str | None = None
    best_bitrate = -1
    for url, bitrate in candidates:
        if bitrate is not None and bitrate > best_bitrate:
            best_url, best_bitrate = url, bitrate
    if best_url is not None:
        return best_url, best_bitrate
    return candidates[0]


def _video_from_component(component: Mapping, page: object) -> list[MediaEntry]:
    """One `MediaVideoPending` from a ``linkedInVideoComponent`` and its resolved VPM.

    ``page`` is the `xbrain.linkedin.bpr.ParsedPage` — used to ``deref`` the
    ``*videoPlayMetadata`` URN reference against the entity pool.
    """
    ref = component.get("*videoPlayMetadata")
    deref = getattr(page, "deref", None)
    vpm = deref(ref) if callable(deref) else None
    if not isinstance(vpm, Mapping):
        return []
    url, bitrate = _pick_video_stream(vpm)
    if not url:
        return []
    thumbnail = vpm.get("thumbnail")
    thumb_url = _vector_image_url(thumbnail) if isinstance(thumbnail, Mapping) else None
    duration = vpm.get("duration")
    return [
        MediaVideoPending(
            url=url,
            thumbnail_url=thumb_url,
            bitrate=bitrate,
            duration_millis=duration if isinstance(duration, int) else None,
        )
    ]


def _external_share(component: Mapping) -> PostContent | None:
    """Map an ``EXTERNAL_FULL`` ``articleComponent`` to a link-share `PostContent`."""
    if component.get("type") != _EXTERNAL_SHARE_TYPE:
        return None
    nav = component.get("navigationContext")
    target = nav.get("actionTarget", "") if isinstance(nav, Mapping) else ""
    if not isinstance(target, str) or not target:
        return None
    title = _text_of(component.get("title"))
    description = _text_of(component.get("description"))
    text = f"{title}\n\n{description}".strip() if description else title
    return PostContent(
        text=text,
        author=None,
        media=[],
        links=[Link(url=target, domain=urlparse(target).netloc)],
        is_external_share=True,
    )


def _find_link_in(node: object, depth: int = 0) -> str | None:
    """Best-effort: recursively find a URL under a body-text attribute range.

    UNVALIDATED against production — ``commentary.text.attributes`` was ``null``
    in all 7 reconnaissance samples. We look for a ``url`` / ``actionTarget``
    string anywhere in the range's nested ``detailData`` / ``*link`` structure.
    A shape we do not recognise yields ``None`` (no link) rather than a raise.
    """
    if depth > 6 or not isinstance(node, Mapping):
        return None
    for key in ("url", "actionTarget"):
        value = node.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    for value in node.values():
        if isinstance(value, Mapping):
            found = _find_link_in(value, depth + 1)
            if found:
                return found
    return None


def _inline_links(update: Mapping) -> list[Link]:
    """Best-effort external links from ``commentary.text.attributes`` hyperlink ranges."""
    commentary = update.get("commentary")
    if not isinstance(commentary, Mapping):
        return []
    text_node = commentary.get("text")
    if not isinstance(text_node, Mapping):
        return []
    ranges = text_node.get("attributes") or text_node.get("attributesV2")
    if not isinstance(ranges, list):
        return []
    links: list[Link] = []
    seen: set[str] = set()
    for entry in ranges:
        url = _find_link_in(entry)
        if url and url not in seen:
            seen.add(url)
            links.append(Link(url=url, domain=urlparse(url).netloc))
    return links


def _content_component(update: Mapping) -> Mapping:
    """``update.content`` as a mapping (``{}`` when absent/malformed)."""
    content = update.get("content")
    return content if isinstance(content, Mapping) else {}


def map_update(update: Mapping, page: object) -> PostContent:
    """Map a parsed ``Update`` entity to a `PostContent`.

    ``page`` is the `xbrain.linkedin.bpr.ParsedPage` carrying the entity pool,
    needed to resolve the video's ``*videoPlayMetadata`` reference. Never raises:
    an unrecognised ``content`` component degrades to a text-only
    `PostContent` with ``is_unknown_component=True``.
    """
    content = _content_component(update)

    article = content.get("articleComponent")
    if isinstance(article, Mapping):
        share = _external_share(article)
        if share is not None:
            return share

    body = _commentary_text(update)
    author = _author_of(update)
    links = _inline_links(update)

    image_component = content.get("imageComponent")
    if isinstance(image_component, Mapping):
        return PostContent(
            text=body,
            author=author,
            media=_photos_from_image_component(image_component),
            links=links,
        )

    video_component = content.get("linkedInVideoComponent")
    if isinstance(video_component, Mapping):
        return PostContent(
            text=body,
            author=author,
            media=_video_from_component(video_component, page),
            links=links,
        )

    non_null = [k for k, v in content.items() if v is not None and not k.startswith("$")]
    logger.warning("LinkedIn post has no recognised content component (present: %s)", non_null)
    return PostContent(
        text=body,
        author=author,
        media=[],
        links=links,
        is_unknown_component=True,
    )
