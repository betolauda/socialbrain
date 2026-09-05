"""Per-platform, per-language wording written by the note renderer.

Fork addition (see `docs/FORK.md`). Deliberately NOT folded into
`xbrain.i18n.Strings`: those vary by *language* only (Topics/Content/
Summary/...), so adding a language there stays a one-entry edit. This
module's strings vary by *platform × language* (X says "Tweet", LinkedIn
says "Post"; both exist in English and Spanish) — folding a second axis
into `Strings` would turn "add a language" into an N-entry edit for every
existing platform, exactly what upstream's own docstring says the design
avoids.

Every call site in `generate.py` takes a `PlatformStrings` parameter
defaulting to `X_DEFAULT`, so every pre-fork call site and every existing
test keeps producing byte-identical output without passing anything new.
`X_DEFAULT` reproduces xbrain's original literals character-for-character:
"Tweet", "Ver tweet original", "Enlaces", "x-knowledge", "Bookmarks",
"Tweets propios".
"""

from __future__ import annotations

from dataclasses import dataclass

from xbrain.models import SourceName
from xbrain.platforms import PlatformName

# "Enlaces" is intentionally the SAME string for every platform and BOTH
# languages: it was already hardcoded Spanish regardless of output_language
# before this fork (a pre-existing upstream quirk, not something this fork's
# scope is to fix — doing so would change existing English-output byte
# content for reasons unrelated to a second source). Kept as one shared
# constant so no per-platform variant can accidentally drift from it.
_LINKS_HEADER = "Enlaces"


@dataclass(frozen=True)
class PlatformStrings:
    post_heading: str  # "Tweet" / "Post"
    view_original: str  # "Ver tweet original" / "Ver post original"
    links_header: str  # "Enlaces" — identical across platforms/languages
    vault_tag: str  # "x-knowledge" / "linkedin-knowledge"
    source_labels: dict[SourceName, str]  # for `_render_index`'s counters


# X's wording is deliberately the SAME regardless of `output_language`: none
# of "## Tweet" / "Ver tweet original" / "Bookmarks · Tweets propios" ever
# went through `i18n.Strings` before this fork — they were hardcoded
# literals, ignored by the language setting, exactly like `_LINKS_HEADER`
# above. Giving X a real English variant here would be a genuine behaviour
# change for existing `output.language = "English"` users, unrelated to
# adding LinkedIn. Only LinkedIn (new content, no legacy byte-output to
# preserve) gets to vary properly by language.
_X_STRINGS = PlatformStrings(
    post_heading="Tweet",
    view_original="Ver tweet original",
    links_header=_LINKS_HEADER,
    vault_tag="x-knowledge",
    source_labels={"bookmark": "Bookmarks", "own_tweet": "Tweets propios"},
)

_PLATFORM_STRINGS: dict[tuple[PlatformName, str], PlatformStrings] = {
    ("linkedin", "Spanish"): PlatformStrings(
        post_heading="Post",
        view_original="Ver post original",
        links_header=_LINKS_HEADER,
        vault_tag="linkedin-knowledge",
        source_labels={"li_saved": "Guardados de LinkedIn"},
    ),
    ("linkedin", "English"): PlatformStrings(
        post_heading="Post",
        view_original="View original post",
        links_header=_LINKS_HEADER,
        vault_tag="linkedin-knowledge",
        source_labels={"li_saved": "LinkedIn saved posts"},
    ),
}

# Reproduces xbrain's pre-fork literals exactly — the default for every
# `generate.py` call site so nothing changes unless a caller opts in.
X_DEFAULT: PlatformStrings = _X_STRINGS


def platform_strings_for(platform: PlatformName, language: str) -> PlatformStrings:
    """The wording for one platform in one output language.

    `language` must already be a supported one — call `xbrain.i18n.strings_for`
    first (as `generate()` does) to get the same "unsupported language" error
    for both string sets from a single source of truth. X ignores `language`
    entirely (see `_X_STRINGS`); only LinkedIn actually varies by it.
    """
    if platform == "x":
        return _X_STRINGS
    return _PLATFORM_STRINGS[(platform, language)]
