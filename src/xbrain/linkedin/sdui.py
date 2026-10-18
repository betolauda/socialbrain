"""Parse a rendered LinkedIn post page (the SDUI ``UpdateDetail`` screen).

LinkedIn used to inline the post as Voyager JSON in ``<code id="bpr-guid-…">``
blocks; by October 2026 it serves a server-driven-UI page instead and the post only
exists as rendered DOM (no BPR block, and no ``/voyager/api/`` response carries it).
This module is **pure** — an HTML string in, a `PageOutcome` out; no browser, no
network. Everything about the page's shape lives here so a LinkedIn change is one
file and one failing test, not a debugging session.

Anchors relied on (all read off real captures; class names are obfuscated and are
never used):

- **container** — the element whose ``data-testid`` contains ``commentList`` (the
  whole feed-detail column: post card first, then reactions and comments).
- **post card** — the container's first element child.
- **identity** — every ``/feed/update/urn:li:activity:<id>/`` anchor inside the
  container. They must all carry the requested id: a different one means a reshare
  or another post, and the page is NOT hydrated. (The reactions
  ``data-testid`` is not usable: it holds a ``ugcPost`` id for some posts.)
- **body** — the card's first ``data-testid="expandable-text-box"``. The DOM holds
  the full text even when it is visually clamped; a ``expandable-text-button``
  *inside the card* would mean a truncated body and the page is rejected rather than
  stored as a fragment (comments have such buttons; they are not read).
- **author** — the first ``/in/``, ``/company/`` or ``/school/`` anchor in the card
  that carries text and is not inside the body; its name is the first ``<p><span>``.
  The page sidebar is the *viewer's* own profile, so nothing outside the card is read.
- **media** — card images by CDN kind: ``feedshare-*`` photos and
  ``ads-document-images_*`` document pages; ``videocover-*`` is a video's poster.
  ``image-shrink_*`` (a link card's thumbnail) is skipped silently. Avatars (``profile-displayphoto-*``, ``company-logo*``) are ignored.
  The ``<video>`` source is a ``blob:`` URL, so a video is recorded poster-era
  (``url == thumbnail_url``, the existing convention `xbrain.video_media` already
  treats as not-downloadable) — registered as a video, never as a photo.
- **links** — ``/safety/go/?url=…`` wrappers (unwrapped) and plain external anchors.

A removed post has no container and a notice; that pair — both — is a terminal
``deleted``. Anything else that does not parse is ``unrecognized`` with the missing
anchors named in ``reason``, which the hydrator records as a transient failure.

``lxml`` is used directly; it is a dependency of ``trafilatura``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import parse_qs, urlparse

from lxml import etree
from lxml import html as lxml_html

from xbrain.models import Author, Link, MediaEntry, MediaPhotoPending, MediaVideoPending

logger = logging.getLogger(__name__)

_ACTIVITY_HREF = re.compile(r"/feed/update/urn:li:activity:(\d+)")
_IMAGE_KIND = re.compile(r"/dms/image/v\d+/[^/]+/([\w\-]+)/")
# A <video> poster can also be served from the playlist CDN path, not /dms/image/.
_PLAYLIST_POSTER = "/playlist/vid/"
_PROFILE_PATH = re.compile(r"^/(in|company|school)/([^/?#]+)")

# CDN image kinds that are not post content.
_AVATAR_KINDS = ("profile-displayphoto", "profile-framedphoto", "company-logo")
# A link card's thumbnail (the link itself is captured separately). Inferred from
# real runs: it only appeared on posts whose sole attachment was an external link.
_DECORATIVE_KINDS = ("image-shrink",)
# Pages of a document / carousel post: post content, one image per page.
_PHOTO_KINDS = ("feedshare", "ads-document-images")

# Notices LinkedIn shows for a removed post, matched case-insensitively. Only the
# Spanish one is confirmed against a capture; the others are best effort. A miss is
# the SAFE direction: the page is `unrecognized` (transient, retried), never a live
# post marked dead because the account language changed.
_GONE_PHRASES = (
    "la publicación se ha retirado o eliminado",
    "no se ha encontrado la publicación",
    "this post has been removed or deleted",
    "post not found",
    "a publicação foi removida ou excluída",
    "publicação não encontrada",
)


@dataclass(frozen=True)
class PostContent:
    """Fields extracted from a post, ready to apply to an `Item` stub.

    - ``warnings`` — anchors that were absent or things not understood
      (``author``, ``image:<kind>``, ``video:no-cover``); the caller logs them.
    - ``is_unknown_component`` — an image kind or video we do not map was seen:
      the post is hydrated text-only for that part, never mis-mapped.
    """

    text: str = ""
    author: Author | None = None
    media: list[MediaEntry] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    is_unknown_component: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PageOutcome:
    """What a page turned out to be.

    ``kind`` is ``post`` (``content`` set), ``deleted`` (terminal) or ``unrecognized``
    (``reason`` names the missing/contradicting anchors: ``container``,
    ``identity:…``, ``truncated_body`` …).
    """

    kind: Literal["post", "deleted", "unrecognized"]
    content: PostContent | None = None
    reason: str = ""


def _unrecognized(reason: str) -> PageOutcome:
    return PageOutcome(kind="unrecognized", reason=reason)


def _text_with_breaks(element: etree._Element) -> str:
    """The element's text with ``<br>`` as newlines, whitespace tidied per line."""
    for br in element.xpath(".//br"):
        br.tail = "\n" + (br.tail or "")
    raw = "".join(element.itertext())
    lines = [" ".join(line.split()) for line in raw.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _is_gone_page(doc: etree._Element) -> bool:
    text = " ".join(doc.text_content().lower().split())
    return any(phrase in text for phrase in _GONE_PHRASES)


def _author(card: etree._Element) -> Author | None:
    for anchor in card.xpath(".//a[@href]"):
        if anchor.xpath("ancestor::*[@data-testid='expandable-text-box']"):
            continue
        match = _PROFILE_PATH.match(urlparse(anchor.get("href")).path)
        if match is None:
            continue
        spans = anchor.xpath(".//p[1]//span[1]")
        name = " ".join(spans[0].text_content().split()) if spans else ""
        name = name or " ".join(anchor.text_content().split())
        if name:
            return Author(handle=match.group(2), name=name)
    return None


def _media(card: etree._Element) -> tuple[list[MediaEntry], bool, list[str]]:
    media: list[MediaEntry] = []
    seen: set[str] = set()
    warnings: list[str] = []
    cover_seen = False
    for image in card.xpath(".//img[@src]"):
        src = image.get("src")
        match = _IMAGE_KIND.search(src)
        kind = (
            match.group(1) if match else ("videocover-playlist" if _PLAYLIST_POSTER in src else "?")
        )
        if kind.startswith(_AVATAR_KINDS + _DECORATIVE_KINDS) or src in seen:
            continue
        seen.add(src)
        if kind.startswith(_PHOTO_KINDS):
            media.append(MediaPhotoPending(url=src))
        elif kind.startswith("videocover"):
            cover_seen = True
            media.append(MediaVideoPending(url=src, thumbnail_url=src))
        else:
            warnings.append(f"image:{kind}")
    if card.xpath(".//video") and not cover_seen:
        warnings.append("video:no-cover")
    return media, bool(warnings), warnings


def _links(card: etree._Element) -> list[Link]:
    found: list[str] = []
    for anchor in card.xpath(".//a[@href]"):
        parsed = urlparse(anchor.get("href"))
        if parsed.path.startswith("/safety/go") and "linkedin.com" in parsed.netloc:
            target = parse_qs(parsed.query).get("url", [""])[0]
        elif parsed.scheme in ("http", "https") and "linkedin.com" not in parsed.netloc:
            target = anchor.get("href")
        else:
            continue
        if target.startswith(("http://", "https://")) and target not in found:
            found.append(target)
    return [Link(url=url, domain=urlparse(url).netloc) for url in found]


def parse_page(page_html: str, urn_id: str | None) -> PageOutcome:
    """Classify a rendered post page and, for a post, extract its content.

    ``urn_id`` is the activity id the page was requested for (``None`` when it is
    unverifiable, e.g. an ``article`` URN): the identity check is skipped then.
    """
    if not page_html.strip():
        return _unrecognized("empty-html")
    try:
        doc = lxml_html.fromstring(page_html)
    except (etree.ParserError, ValueError):
        return _unrecognized("unparseable-html")

    containers = doc.xpath("//*[contains(@data-testid, 'commentList')]")
    if not containers:
        if _is_gone_page(doc):
            return PageOutcome(kind="deleted", reason="removed-notice-without-container")
        return _unrecognized("container")
    container = containers[0]
    cards = [child for child in container if isinstance(child.tag, str)]
    if not cards:
        return _unrecognized("post-card")
    card = cards[0]

    if urn_id is not None:
        ids = {
            match
            for href in container.xpath(".//a/@href")
            for match in _ACTIVITY_HREF.findall(href)
        }
        if not ids:
            return _unrecognized("identity:no-permalink")
        if ids != {urn_id}:
            return _unrecognized(f"identity:mismatch:{sorted(ids)}")

    if card.xpath(".//*[@data-testid='expandable-text-button']"):
        return _unrecognized("truncated_body")

    boxes = card.xpath(".//*[@data-testid='expandable-text-box']")
    media, unknown, warnings = _media(card)
    author = _author(card)
    if author is None:
        warnings.append("author")
    return PageOutcome(
        kind="post",
        content=PostContent(
            text=_text_with_breaks(boxes[0]) if boxes else "",
            author=author,
            media=media,
            links=_links(card),
            is_unknown_component=unknown,
            warnings=warnings,
        ),
    )
