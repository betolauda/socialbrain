# tests/test_platform_strings.py
from xbrain.platform_strings import X_DEFAULT, platform_strings_for


def test_x_default_reproduces_original_literals():
    """Pins the exact pre-fork wording — anyone editing X_DEFAULT is
    changing existing X output, not just adding a LinkedIn variant."""
    assert X_DEFAULT.post_heading == "Tweet"
    assert X_DEFAULT.view_original == "Ver tweet original"
    assert X_DEFAULT.links_header == "Enlaces"
    assert X_DEFAULT.vault_tag == "x-knowledge"
    assert X_DEFAULT.source_labels == {"bookmark": "Bookmarks", "own_tweet": "Tweets propios"}


def test_platform_strings_for_x_spanish_is_the_default():
    assert platform_strings_for("x", "Spanish") == X_DEFAULT


def test_platform_strings_for_linkedin_spanish():
    ps = platform_strings_for("linkedin", "Spanish")
    assert ps.post_heading == "Post"
    assert ps.view_original == "Ver post original"
    assert ps.links_header == "Enlaces"
    assert ps.vault_tag == "linkedin-knowledge"
    assert ps.source_labels == {"li_saved": "Guardados de LinkedIn"}


def test_links_header_is_identical_across_every_platform_and_language():
    """Deliberate: "Enlaces" is a pre-existing hardcoded-Spanish quirk in
    xbrain, unrelated to this fork's scope to fix — see module docstring."""
    for platform in ("x", "linkedin"):
        for language in ("English", "Spanish"):
            assert platform_strings_for(platform, language).links_header == "Enlaces"
