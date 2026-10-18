"""Tests for `xbrain.linkedin.sdui` — parsing a rendered LinkedIn post page.

Fixtures are synthetic (`tests/linkedin_html.py`), modelled on the structure of real
captures and containing no real content.
"""

from __future__ import annotations

import pytest

from tests.linkedin_html import deleted_page, img, post_page, safety_link
from xbrain.linkedin import sdui
from xbrain.models import MediaPhotoPending, MediaVideoPending


def _post(page: str, urn_id: str | None = "111") -> sdui.PostContent:
    outcome = sdui.parse_page(page, urn_id)
    assert outcome.kind == "post", outcome.reason
    assert outcome.content is not None
    return outcome.content


# ----------------------------------------------------------------- text & author


def test_text_only_post() -> None:
    content = _post(post_page(body="Hello world"))
    assert content.text == "Hello world"
    assert content.media == [] and content.links == []
    assert not content.is_unknown_component


def test_person_author_is_the_post_card_not_the_viewer_in_the_sidebar() -> None:
    content = _post(post_page(author=("Ada Example", "ada-example", "in")))
    assert content.author is not None
    assert (content.author.name, content.author.handle) == ("Ada Example", "ada-example")


def test_company_author() -> None:
    content = _post(post_page(author=("Acme Corp", "acme-corp", "company")))
    assert content.author is not None
    assert (content.author.name, content.author.handle) == ("Acme Corp", "acme-corp")


def test_line_breaks_in_the_body_are_kept() -> None:
    content = _post(post_page(body="first<br>second<br><br>third"))
    assert content.text == "first\nsecond\n\nthird"


def test_missing_author_is_a_warning_not_a_failure() -> None:
    content = _post(post_page(author=None))
    assert content.author is None
    assert "author" in content.warnings


def test_post_without_body_is_still_a_post() -> None:
    content = _post(post_page(body=None, media=[img("feedshare-shrink_480")]))
    assert content.text == "" and len(content.media) == 1


# ------------------------------------------------------------------------- media


def test_photos_are_the_feedshare_images_only_in_order_without_avatars() -> None:
    page = post_page(media=[img("feedshare-shrink_480", "a"), img("feedshare-shrink_800", "b")])
    media = _post(page).media
    assert [type(m) for m in media] == [MediaPhotoPending, MediaPhotoPending]
    assert media[0].url.endswith("/a?e=1&v=beta&t=tok") and media[1].url.endswith(
        "/b?e=1&v=beta&t=tok"
    )


def test_the_same_photo_twice_is_one_entry() -> None:
    photo = img("feedshare-shrink_480", "same")
    assert len(_post(post_page(media=[photo, photo])).media) == 1


def test_video_is_registered_as_a_video_with_its_cover_not_as_a_photo() -> None:
    page = post_page(media=[img("videocover-low", "cov"), '<video src="blob:https://x/1"></video>'])
    media = _post(page).media
    assert len(media) == 1 and isinstance(media[0], MediaVideoPending)
    # poster-era convention (url == thumbnail_url): never a downloadable stream
    assert media[0].url == media[0].thumbnail_url and media[0].url.endswith("/cov?e=1&v=beta&t=tok")


def test_unknown_image_kind_is_flagged_not_dropped_silently() -> None:
    content = _post(post_page(media=[img("document-cover_800")]))
    assert content.is_unknown_component
    assert "image:document-cover_800" in content.warnings


def test_video_without_cover_is_flagged_unknown() -> None:
    content = _post(post_page(media=['<video src="blob:https://x/1"></video>']))
    assert content.is_unknown_component and "video:no-cover" in content.warnings


# ------------------------------------------------------------------------- links


def test_external_links_are_unwrapped_from_the_safety_redirect() -> None:
    body = f"read {safety_link('https://lnkd.in/abc-1')} and more"
    links = _post(post_page(body=body)).links
    assert [(link.url, link.domain) for link in links] == [("https://lnkd.in/abc-1", "lnkd.in")]


def test_link_card_outside_the_body_counts_and_duplicates_collapse() -> None:
    page = post_page(
        body=safety_link("https://example.org/a"),
        media=[safety_link("https://example.org/a"), safety_link("https://example.org/b")],
    )
    assert [link.url for link in _post(page).links] == [
        "https://example.org/a",
        "https://example.org/b",
    ]


def test_mentions_and_hashtags_are_not_links() -> None:
    body = (
        '<a href="https://www.linkedin.com/in/someone/">Someone</a> '
        '<a href="https://www.linkedin.com/search/results/all/?keywords=%23tag">#tag</a>'
    )
    assert _post(post_page(body=body)).links == []


# ---------------------------------------------------------------------- identity


def test_a_ugcpost_facepile_is_fine_when_the_permalinks_carry_the_requested_id() -> None:
    page = post_page("111", facepile="urn:li:ugcPost:999")
    assert sdui.parse_page(page, "111").kind == "post"


def test_a_different_activity_id_in_the_container_makes_the_page_suspicious() -> None:
    page = post_page("111", permalink_ids=["111", "222"])  # e.g. a reshare of another post
    outcome = sdui.parse_page(page, "111")
    assert outcome.kind == "unrecognized"
    assert "identity" in outcome.reason and "222" in outcome.reason


def test_a_page_about_another_post_is_not_hydrated() -> None:
    outcome = sdui.parse_page(post_page("999"), "111")
    assert outcome.kind == "unrecognized" and "identity" in outcome.reason


def test_no_permalink_in_the_container_cannot_be_verified() -> None:
    outcome = sdui.parse_page(post_page("111", permalink_ids=[]), "111")
    assert outcome.kind == "unrecognized" and "permalink" in outcome.reason


def test_without_an_activity_id_the_identity_check_is_skipped() -> None:
    assert sdui.parse_page(post_page("111", permalink_ids=["abc"]), None).kind == "post"


# ------------------------------------------------------------- truncation / gone


def test_a_truncated_post_body_is_not_accepted_as_complete() -> None:
    outcome = sdui.parse_page(post_page(truncated=True), "111")
    assert outcome.kind == "unrecognized" and "truncated" in outcome.reason


def test_a_see_more_button_on_a_comment_is_irrelevant() -> None:
    assert sdui.parse_page(post_page(comments=3), "111").kind == "post"


@pytest.mark.parametrize(
    "message",
    [
        "La publicación se ha retirado o eliminado.",
        "This post has been removed or deleted.",
        "A publicação foi removida ou excluída.",
    ],
)
def test_a_removed_post_needs_no_container_and_the_notice_in_any_language(message: str) -> None:
    assert sdui.parse_page(deleted_page(message), "111").kind == "deleted"


def test_no_container_and_no_notice_is_unrecognized_not_deleted() -> None:
    blank = sdui.parse_page("<html><body><main>nothing</main></body></html>", "111")
    assert blank.kind == "unrecognized" and "container" in blank.reason


def test_the_notice_alone_does_not_condemn_a_page_that_has_the_container() -> None:
    page = post_page(body="the post has been removed or deleted, they said")
    assert sdui.parse_page(page, "111").kind == "post"


def test_empty_html_is_unrecognized() -> None:
    assert sdui.parse_page("", "111").kind == "unrecognized"
