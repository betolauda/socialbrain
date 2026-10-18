"""Synthetic LinkedIn post-page HTML for the SDUI parser tests.

Modelled on the *structure* of real captured post pages (the `UpdateDetail` SDUI
screen) — never on their content: every name, text and URL here is invented, so the
repo carries nobody's posts. Only the anchors the parser relies on are reproduced
(container `data-testid`, permalink anchors, `expandable-text-box`, image kinds,
`/safety/go/` link wrapper); the real page's obfuscated class names and wrapper
divs are left out on purpose so the tests do not break on page noise.
"""

from __future__ import annotations

from urllib.parse import quote

_CDN = "https://media.licdn.com/dms/image/v2/AAAA/{kind}/BBBB/CCCC?e=1&amp;v=beta&amp;t=tok"


def img(kind: str, tag: str = "x") -> str:
    """One CDN image of a given kind (`feedshare-shrink_480`, `profile-displayphoto-…`)."""
    return f'<figure><img src="{_CDN.format(kind=kind).replace("CCCC", tag)}"></figure>'


def safety_link(target: str, label: str = "link") -> str:
    """LinkedIn's outbound-link wrapper around an external URL."""
    return f'<a href="https://www.linkedin.com/safety/go/?url={quote(target, safe="")}">{label}</a>'


def post_page(
    urn_id: str = "111",
    *,
    body: str | None = "Hello world",
    author: tuple[str, str, str] | None = ("Ada Example", "ada-example", "in"),
    media: list[str] | None = None,
    permalink_ids: list[str] | None = None,
    facepile: str | None = None,
    truncated: bool = False,
    comments: int = 1,
    sidebar: bool = True,
) -> str:
    """A post page with the container, the post card, reactions and comments."""
    ids = [urn_id] if permalink_ids is None else permalink_ids
    permalinks = "".join(
        f'<a href="https://www.linkedin.com/feed/update/urn:li:activity:{i}/"></a>' for i in ids
    )
    card = ""
    if author is not None:
        name, slug, kind = author
        profile = f"https://www.linkedin.com/{kind}/{slug}/"
        card += f'<a href="{profile}">{img("profile-displayphoto-shrink_100_100")}</a>'
        card += (
            f'<a href="{profile}"><div><p><span>{name}</span></p><p><span>• 2º</span></p></div></a>'
        )
        card += f'<a href="{profile}"></a>'
    if body is not None:
        card += f'<p><span data-testid="expandable-text-box">{body}</span></p>'
    if truncated:
        card += '<button data-testid="expandable-text-button">… más</button>'
    card += "".join(media or []) + permalinks
    reactions = (
        f"<div>{permalinks}"
        f"{img('profile-displayphoto-shrink_100_100')}{img('profile-displayphoto-scale_100_100')}"
        "</div>"
    )
    comment = (
        f"<div>{img('profile-displayphoto-shrink_100_100')}"
        '<p><span data-testid="expandable-text-box">a comment</span></p>'
        '<button data-testid="expandable-text-button">… más</button></div>'
    )
    facepile_id = facepile or f"urn:li:activity:{urn_id}"
    container = (
        '<div data-component-type="LazyColumn" '
        'data-testid="Zm9vcommentListQmFyFeedType_FEED_DETAIL">'
        f"<div>{card}</div>{reactions}"
        f'<div data-testid="ReactionFacepileCollection-{facepile_id}"></div>'
        f"{comment * comments}</div>"
    )
    viewer = (
        '<aside><a href="https://www.linkedin.com/in/the-viewer/">'
        f"{img('profile-displayphoto-shrink_100_100')}</a>"
        '<a href="https://www.linkedin.com/in/the-viewer/"><p><span>Viewer Person</span></p></a>'
        "</aside>"
        if sidebar
        else ""
    )
    return (
        "<html><head><title>Publicación | LinkedIn</title></head><body>"
        f'<div data-sdui-screen="com.linkedin.sdui.flagshipnav.feed.UpdateDetail">{viewer}'
        f"<main>{container}</main></div></body></html>"
    )


def deleted_page(message: str = "La publicación se ha retirado o eliminado.") -> str:
    """The page LinkedIn serves for a removed post: no container, a notice instead."""
    return (
        "<html><head><title>Publicación | LinkedIn</title></head><body>"
        '<div data-sdui-screen="com.linkedin.sdui.flagshipnav.feed.UpdateDetail">'
        f"<aside><a href='https://www.linkedin.com/in/the-viewer/'>Viewer Person</a></aside>"
        f"<main><div><h2>No se ha encontrado la publicación</h2><p>{message}</p></div></main>"
        "</div></body></html>"
    )
