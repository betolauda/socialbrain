"""Tests for xbrain.linkedin.browser — session-death detection.

`login()` opens a real browser and blocks on stdin, so it is not unit
tested here (same as xbrain.extract.browser.login). `is_logged_out` is the
pure, testable core.
"""

from __future__ import annotations

import pytest

from xbrain.linkedin.browser import is_logged_out


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/login",
        "https://www.linkedin.com/uas/login?session_redirect=%2Ffeed",
        "https://www.linkedin.com/authwall?trk=bf",
        "https://www.linkedin.com/checkpoint/challenge/verify",
        "https://www.linkedin.com/checkpoint/lg/login-submit",
        "https://www.linkedin.com/m/login/",
    ],
)
def test_is_logged_out_detects_login_authwall_and_checkpoint(url: str) -> None:
    assert is_logged_out(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/feed/",
        "https://www.linkedin.com/feed/update/urn:li:activity:7495649402552913920/",
        "https://www.linkedin.com/in/some-person/",
        "https://www.linkedin.com/my-items/saved-posts/",
    ],
)
def test_is_logged_out_false_for_real_content(url: str) -> None:
    assert not is_logged_out(url)
