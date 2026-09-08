"""Tests for `xbrain.linkedin.post` — mapping an ``Update`` entity to `PostContent`.

Every fixture is constructed inline from the *shape* recorded during
reconnaissance (docs/LINKEDIN_HYDRATE.md) — never copied from `linkedin_data/`.
Invented names, invented text, invented ids and URLs throughout.
"""

from __future__ import annotations

from xbrain.linkedin import post
from xbrain.linkedin.bpr import ParsedPage
from xbrain.models import MediaPhotoPending, MediaVideoPending

_ROOT = "https://cdn.example.test/dms/image/v2/AAA/feedshare-shrink_"


def _text_node(value: str) -> dict:
    return {"text": value, "textDirection": "FIRST_STRONG"}


def _artifact(width: int, segment: str) -> dict:
    return {"width": width, "height": width, "fileIdentifyingUrlPathSegment": segment}


def _image(root: str, artifacts: list[dict]) -> dict:
    return {
        "attributes": [{"detailData": {"vectorImage": {"rootUrl": root, "artifacts": artifacts}}}]
    }


def _update(**overrides: object) -> dict:
    base: dict = {"content": {}, "commentary": None, "actor": None}
    base.update(overrides)
    return base


def _page(update: dict, pool: dict | None = None) -> ParsedPage:
    return ParsedPage(update=update, pool=pool or {})


def test_body_text_is_read_from_commentary() -> None:
    update = _update(commentary={"text": _text_node("Line one\n\nLine two")})

    result = post.map_update(update, _page(update))

    assert result.text == "Line one\n\nLine two"
    assert result.is_unknown_component is True  # no content component present


def test_missing_commentary_yields_empty_text() -> None:
    update = _update(commentary=None)

    assert post.map_update(update, _page(update)).text == ""


def test_author_handle_is_parsed_from_the_profile_url() -> None:
    update = _update(
        commentary={"text": _text_node("hi")},
        actor={
            "name": _text_node("Dana Example"),
            "navigationContext": {
                "actionTarget": "https://www.linkedin.com/in/dana-example?miniProfileUrn=urn%3Ax"
            },
        },
        content={"imageComponent": {"images": []}},
    )

    author = post.map_update(update, _page(update)).author

    assert author is not None
    assert author.name == "Dana Example"
    assert author.handle == "dana-example"


def test_single_image_picks_the_largest_artifact() -> None:
    artifacts = [
        _artifact(200, "200/seg-a"),
        _artifact(1280, "1280/seg-b"),
        _artifact(800, "800/seg-c"),
    ]
    update = _update(content={"imageComponent": {"images": [_image(_ROOT, artifacts)]}})

    media = post.map_update(update, _page(update)).media

    assert media == [MediaPhotoPending(url=_ROOT + "1280/seg-b")]


def test_multi_image_carousel_maps_every_image() -> None:
    images = [
        _image(_ROOT, [_artifact(480, f"480/seg-{n}"), _artifact(1080, f"1080/seg-{n}")])
        for n in range(3)
    ]
    update = _update(content={"imageComponent": {"images": images}})

    media = post.map_update(update, _page(update)).media

    assert [m.url for m in media] == [_ROOT + f"1080/seg-{n}" for n in range(3)]


def test_video_resolves_the_ref_to_the_highest_bitrate_mp4() -> None:
    vpm_urn = "urn:li:digitalmediaAsset:V1"
    vpm = {
        "entityUrn": vpm_urn,
        "duration": 16266,
        "thumbnail": {
            "rootUrl": "",
            "artifacts": [_artifact(1280, "https://cdn.example.test/thumb_1280.jpg")],
        },
        "progressiveStreams": [
            {
                "bitRate": 265379,
                "mediaType": "video/mp4",
                "streamingLocations": [{"url": "https://cdn.example.test/360p.mp4"}],
            },
            {
                "bitRate": 579969,
                "mediaType": "video/mp4",
                "streamingLocations": [{"url": "https://cdn.example.test/720p.mp4"}],
            },
        ],
        "adaptiveStreams": [{"masterPlaylists": [{"url": "https://cdn.example.test/master.m3u8"}]}],
    }
    update = _update(content={"linkedInVideoComponent": {"*videoPlayMetadata": vpm_urn}})

    media = post.map_update(update, _page(update, {vpm_urn: vpm})).media

    assert media == [
        MediaVideoPending(
            url="https://cdn.example.test/720p.mp4",
            thumbnail_url="https://cdn.example.test/thumb_1280.jpg",
            bitrate=579969,
            duration_millis=16266,
        )
    ]


def test_video_falls_back_to_hls_when_no_progressive_stream() -> None:
    vpm_urn = "urn:li:digitalmediaAsset:V2"
    vpm = {
        "progressiveStreams": [],
        "adaptiveStreams": [{"masterPlaylists": [{"url": "https://cdn.example.test/master.m3u8"}]}],
    }
    update = _update(content={"linkedInVideoComponent": {"*videoPlayMetadata": vpm_urn}})

    media = post.map_update(update, _page(update, {vpm_urn: vpm})).media

    assert media == [MediaVideoPending(url="https://cdn.example.test/master.m3u8")]


def test_external_full_share_yields_a_link_and_no_media() -> None:
    update = _update(
        content={
            "articleComponent": {
                "type": "EXTERNAL_FULL",
                "navigationContext": {"actionTarget": "https://blog.example.test/spark-guide"},
                "title": _text_node("A Spark Guide"),
                "subtitle": _text_node("blog.example.test"),
                "description": _text_node("Everything about Spark."),
            }
        }
    )

    result = post.map_update(update, _page(update))

    assert result.is_external_share is True
    assert result.media == []
    assert result.author is None
    assert result.links[0].url == "https://blog.example.test/spark-guide"
    assert result.links[0].domain == "blog.example.test"
    assert result.text == "A Spark Guide\n\nEverything about Spark."


def test_unknown_component_degrades_to_text_only_without_raising() -> None:
    update = _update(
        commentary={"text": _text_node("A poll body")},
        content={"pollComponent": {"question": "which?"}},
    )

    result = post.map_update(update, _page(update))

    assert result.text == "A poll body"
    assert result.media == []
    assert result.is_unknown_component is True


def test_constructed_inline_link_attribute_is_extracted_best_effort() -> None:
    """Inline body-link extraction.

    UNVALIDATED against production: ``commentary.text.attributes`` was ``null``
    in all 7 reconnaissance samples. This fixture is a best-effort guess at the
    range shape (a nested ``detailData`` carrying a hyperlink URL); if the real
    production shape differs, `post._inline_links` returns no links rather than
    raising — covered by every other test above, none of which supplies this key.
    """
    update = _update(
        commentary={
            "text": {
                "text": "see how-to-ai.guide for more",
                "attributes": [
                    {
                        "start": 8,
                        "length": 14,
                        "detailData": {"link": {"url": "https://how-to-ai.guide/course"}},
                    }
                ],
            }
        }
    )

    links = post.map_update(update, _page(update)).links

    assert [link.url for link in links] == ["https://how-to-ai.guide/course"]
    assert links[0].domain == "how-to-ai.guide"


def test_actor_with_only_a_name_still_yields_an_author() -> None:
    update = _update(
        commentary={"text": _text_node("hi")},
        actor={"name": _text_node("No Handle"), "navigationContext": {"actionTarget": ""}},
        content={"imageComponent": {"images": []}},
    )

    author = post.map_update(update, _page(update)).author

    assert author is not None
    assert (author.name, author.handle) == ("No Handle", "")


def test_empty_actor_yields_no_author() -> None:
    update = _update(commentary={"text": _text_node("hi")}, actor={})

    assert post.map_update(update, _page(update)).author is None


def test_malformed_image_node_is_skipped_not_raised() -> None:
    update = _update(
        content={"imageComponent": {"images": [{"attributes": []}, {"nope": 1}, "junk"]}}
    )

    result = post.map_update(update, _page(update))

    assert result.media == []
    assert result.is_unknown_component is False


def test_video_ref_absent_from_pool_yields_no_media() -> None:
    update = _update(content={"linkedInVideoComponent": {"*videoPlayMetadata": "urn:li:missing"}})

    assert post.map_update(update, _page(update, {})).media == []


def test_article_component_without_action_target_degrades_to_unknown() -> None:
    update = _update(
        commentary={"text": _text_node("fallback body")},
        content={"articleComponent": {"type": "EXTERNAL_FULL", "navigationContext": {}}},
    )

    result = post.map_update(update, _page(update))

    assert result.text == "fallback body"
    assert result.is_external_share is False
    assert result.is_unknown_component is True


def test_non_external_article_type_is_not_treated_as_a_share() -> None:
    update = _update(
        commentary={"text": _text_node("body")},
        content={"articleComponent": {"type": "NEWSLETTER"}},
    )

    assert post.map_update(update, _page(update)).is_unknown_component is True
