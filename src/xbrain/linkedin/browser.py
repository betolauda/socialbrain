"""Playwright browser session management for LinkedIn.

Mirrors `xbrain.extract.browser` (the X equivalent), kept as a separate
additive module so no core file changes. `login()` opens a visible browser
for a manual sign-in and persists the session; `is_logged_out()` is the
mid-run session-death check the hydrator uses.

The X context helper (`xbrain.extract.browser.x_context`) is reused as-is —
it already takes `storage_state_path` as a parameter and is X-specific in
name only. The LinkedIn session path comes from
`config.storage_state_for("linkedin")` →
`auth/linkedin_storage_state.json` (both added in PR2).
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

# The signed-out landing page. A logged-in browser hitting linkedin.com/feed
# stays there; a dead session bounces to one of the _LOGGED_OUT_MARKERS below.
LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
_FEED_URL = "https://www.linkedin.com/feed/"

# URL fragments that mean "this navigation did not land on real content".
# Unlike X (which only has /login and /i/flow/login), LinkedIn also bounces a
# suspicious or unauthenticated session to an authwall or a checkpoint
# challenge (2FA, "is this you?"). The hydrator MUST tell these apart from a
# genuinely missing post: seeing one of these mid-run means the session died,
# not that 700 posts are all 404 — see docs/LINKEDIN_CAPTURE.md's successor
# design and CLAUDE.md.
_LOGGED_OUT_MARKERS = (
    "/login",
    "/uas/login",
    "/authwall",
    "/checkpoint/",
    "/m/login",
)


def login(storage_state_path: Path) -> None:
    """Open a visible browser so the user can log in to LinkedIn by hand.

    The session (cookies + localStorage) is saved to `storage_state_path`
    once the user confirms they have reached their feed. Mirrors
    `xbrain.extract.browser.login`.
    """
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context()
        context.new_page().goto(LINKEDIN_LOGIN_URL)
        print("Inicia sesión en LinkedIn en la ventana del navegador.")
        print("Cuando veas tu feed, vuelve aquí y pulsa Enter.")
        input()
        context.storage_state(path=str(storage_state_path))
        browser.close()
    print(f"Sesión guardada en {storage_state_path}")


def is_logged_out(page_url: str) -> bool:
    """True if a navigation landed on a login / authwall / checkpoint page.

    Checked after each navigation in the hydrator: a hit here aborts the
    whole run (the session must be renewed with `socialbrain-li login`),
    rather than being misread as a per-post failure.
    """
    return any(marker in page_url for marker in _LOGGED_OUT_MARKERS)
