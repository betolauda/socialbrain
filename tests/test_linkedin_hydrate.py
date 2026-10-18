"""Tests for `xbrain.linkedin.hydrate` — selection/resume + the browser loop.

The loop is exercised with a fake Playwright context/page (no browser, no
network, no real delays). Every HTML fixture is constructed inline from the
reconnaissance *shape* — nothing from `linkedin_data/`.
"""

from __future__ import annotations

import random
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.linkedin_html import deleted_page, post_page
from xbrain.config import load_config
from xbrain.linkedin import hydrate as hydrate_mod
from xbrain.linkedin.hydrate import (
    HydrateReport,
    SessionExpiredError,
    ThrottledError,
    hydrate,
    items_needing_hydration,
)
from xbrain.models import Author, Content, ContentSourceFailure, Item
from xbrain.store import load_store, save_store

_NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _now() -> datetime:
    return _NOW


def _stub(digits: str, *, age_days: int = 0, content: Content | None = None) -> Item:
    created = _NOW - timedelta(days=age_days)
    return Item(
        id=f"li-{digits}",
        source="li_saved",
        url=f"https://www.linkedin.com/feed/update/urn:li:activity:{digits}",
        author=Author(handle="", name=""),
        text="",
        created_at=created,
        captured_at=created,
        content=content,
    )


def _li_failure(reason: str) -> Content:
    return Content(
        fetched_at=_NOW,
        sources=[ContentSourceFailure(kind="li_post", url="https://x.test", failure_reason=reason)],
    )


def _page_html(*, digits: str, body: str) -> str:
    return post_page(digits, body=body)


class _FakePage:
    def __init__(
        self,
        htmls: dict[str, str],
        landed: dict[str, str] | None = None,
        raises: dict[str, BaseException] | None = None,
        statuses: dict[str, int] | None = None,
    ) -> None:
        self._statuses = statuses or {}
        self._htmls = htmls
        self._raises = raises or {}
        self._landed = landed or {}
        self._current = ""
        self.url = ""
        self.goto_urls: list[str] = []

    def goto(self, url: str, wait_until: str | None = None):
        status = self._statuses.get(url)
        self._do_goto(url)
        return SimpleNamespace(status=status) if status is not None else None

    def _do_goto(self, url: str) -> None:
        self.goto_urls.append(url)
        if url in self._raises:
            raise self._raises[url]
        self._current = url
        self.url = self._landed.get(url, url)

    def wait_for_timeout(self, _ms: int) -> None:
        pass

    def content(self) -> str:
        return self._htmls.get(self._current, "<html>nothing here</html>")


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    def new_page(self) -> _FakePage:
        return self._page


def _factory(page: _FakePage):
    @contextmanager
    def _make():
        yield _FakeContext(page)

    return _make


def _cfg(tmp_path: Path, max_per_run: int = 3):
    (tmp_path / "vault").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "config.toml").write_text(
        f'[paths]\nvault = "{tmp_path / "vault"}"\noutput_subdir = "k"\ndata_dir = "data"\n'
        f"[linkedin]\nmax_per_run = {max_per_run}\nmin_delay_s = 20\nmax_delay_s = 20\n",
        encoding="utf-8",
    )
    return load_config(tmp_path)


# --------------------------------------------------------------- selection/resume


def test_transient_failure_is_retried() -> None:
    store = {"li-1": _stub("1", content=_li_failure("timeout"))}
    assert [i.id for i in items_needing_hydration(store, force=False)] == ["li-1"]


def test_terminal_failure_is_skipped_unless_forced() -> None:
    store = {"li-1": _stub("1", content=_li_failure("not_found"))}
    assert items_needing_hydration(store, force=False) == []
    assert [i.id for i in items_needing_hydration(store, force=True)] == ["li-1"]


def test_already_hydrated_item_is_skipped() -> None:
    store = {"li-1": _stub("1", content=Content(fetched_at=_NOW, sources=[]))}
    assert items_needing_hydration(store, force=False) == []


def test_non_li_saved_item_is_never_selected() -> None:
    tweet = Item(
        id="123",
        source="bookmark",
        url="https://x.com/a/status/123",
        author=Author(handle="a", name="A"),
        text="",
        created_at=_NOW,
        captured_at=_NOW,
    )
    assert items_needing_hydration({"123": tweet}, force=False) == []


def test_selection_is_newest_first() -> None:
    store = {
        "li-old": _stub("old", age_days=30),
        "li-new": _stub("new", age_days=1),
        "li-mid": _stub("mid", age_days=10),
    }
    assert [i.id for i in items_needing_hydration(store, force=False)] == [
        "li-new",
        "li-mid",
        "li-old",
    ]


# ------------------------------------------------------------------- the loop


def test_dry_run_reports_selection_and_writes_nothing(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    save_store({"li-1": _stub("1"), "li-2": _stub("2")}, cfg.items_path)

    report = hydrate(cfg, dry_run=True, limit=1, now=_now)

    assert report == HydrateReport(selected=1, dry_run=True)
    assert not cfg.state_path.exists()
    assert not (cfg.data_dir / "snapshots").exists()
    # store file is byte-identical — nothing rewritten
    assert all(item.text == "" for item in load_store(cfg.items_path).values())


def test_limit_caps_the_batch(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    save_store({f"li-{n}": _stub(str(n), age_days=n) for n in range(5)}, cfg.items_path)
    page = _FakePage({})

    report = hydrate(
        cfg,
        limit=2,
        now=_now,
        context_factory=_factory(page),
        sleep=lambda _s: None,
        rng=random.Random(0),
    )

    assert report.selected == 2
    assert len(page.goto_urls) == 2


def test_normal_post_is_hydrated_onto_the_stub(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    save_store({"li-1": _stub("1")}, cfg.items_path)
    url = "https://www.linkedin.com/feed/update/urn:li:activity:1"
    page = _FakePage({url: _page_html(digits="1", body="Hydrated body")})

    report = hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=lambda _s: None,
        rng=random.Random(0),
    )

    assert (report.hydrated, report.failed) == (1, 0)
    stored = load_store(cfg.items_path)["li-1"]
    assert stored.text == "Hydrated body"
    assert stored.content is not None and stored.content.sources == []
    assert load_config(tmp_path).repo_root == tmp_path


def test_a_404_page_without_update_records_a_terminal_not_found(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    save_store({"li-1": _stub("1")}, cfg.items_path)
    url = "https://www.linkedin.com/feed/update/urn:li:activity:1"
    page = _FakePage({}, statuses={url: 404})

    report = hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=lambda _s: None,
        rng=random.Random(0),
    )

    assert (report.hydrated, report.failed) == (0, 1)
    stored = load_store(cfg.items_path)["li-1"]
    assert stored.content is not None
    source = stored.content.sources[0]
    assert isinstance(source, ContentSourceFailure)
    assert source.kind == "li_post" and source.failure_reason == "not_found"


def test_a_strangers_post_is_never_written_onto_the_stub(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    save_store({"li-1": _stub("1")}, cfg.items_path)
    url = "https://www.linkedin.com/feed/update/urn:li:activity:1"
    # the page for post 1 only carries post 999 (e.g. a redirect to the feed)
    page = _FakePage({url: _page_html(digits="999", body="Someone else's text")})

    report = hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=lambda _s: None,
        rng=random.Random(0),
    )

    assert report.hydrated == 0
    assert load_store(cfg.items_path)["li-1"].text == ""


def _three_posts(cfg) -> tuple[str, str, str]:
    save_store({f"li-{n}": _stub(str(n), age_days=n) for n in (1, 2, 3)}, cfg.items_path)
    return tuple(f"https://www.linkedin.com/feed/update/urn:li:activity:{n}" for n in (1, 2, 3))


def test_a_navigation_timeout_fails_that_post_only_and_the_batch_continues(
    tmp_path: Path,
) -> None:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    cfg = _cfg(tmp_path)
    u1, u2, u3 = _three_posts(cfg)
    page = _FakePage(
        {u1: _page_html(digits="1", body="one"), u3: _page_html(digits="3", body="three")},
        raises={u2: PlaywrightTimeout("Timeout 30000ms exceeded")},
    )

    report = hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=lambda _s: None,
        rng=random.Random(0),
    )

    assert (report.hydrated, report.failed) == (2, 1)
    stored = load_store(cfg.items_path)
    assert stored["li-1"].text == "one" and stored["li-3"].text == "three"
    failure = stored["li-2"].content.sources[0]
    assert isinstance(failure, ContentSourceFailure)
    assert failure.failure_reason == "timeout"  # transient: retried next run
    assert [i.id for i in items_needing_hydration(stored, force=False)] == ["li-2"]


def test_an_unexpected_browser_error_is_recorded_as_a_transient_failure(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    u1, u2, u3 = _three_posts(cfg)
    page = _FakePage({}, raises={u2: RuntimeError("Target closed")})

    hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=lambda _s: None,
        rng=random.Random(0),
    )

    failure = load_store(cfg.items_path)["li-2"].content.sources[0]
    assert failure.failure_reason == "unknown_error"
    assert "Target closed" in (failure.error or "")


def test_ctrl_c_mid_run_still_persists_the_posts_already_hydrated(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    u1, u2, u3 = _three_posts(cfg)
    page = _FakePage({u1: _page_html(digits="1", body="one")}, raises={u2: KeyboardInterrupt()})

    with pytest.raises(KeyboardInterrupt):
        hydrate(
            cfg,
            now=_now,
            context_factory=_factory(page),
            sleep=lambda _s: None,
            rng=random.Random(0),
        )

    stored = load_store(cfg.items_path)
    assert stored["li-1"].text == "one"
    assert stored["li-2"].content is None  # interrupted, not failed


def _many_posts(cfg, count: int) -> _FakePage:
    save_store({f"li-{n}": _stub(str(n), age_days=n) for n in range(1, count + 1)}, cfg.items_path)
    base = "https://www.linkedin.com/feed/update/urn:li:activity:"
    return _FakePage(
        {f"{base}{n}": _page_html(digits=str(n), body=f"post {n}") for n in range(1, count + 1)}
    )


def _hydrated_on_disk(cfg) -> int:
    return sum(1 for i in load_store(cfg.items_path).values() if i.text)


def test_progress_is_saved_every_few_posts_not_only_at_the_end(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, max_per_run=12)
    page = _many_posts(cfg, 12)
    seen_on_disk: list[int] = []

    def _spy_sleep(_s: float) -> None:  # runs before every post but the first
        seen_on_disk.append(_hydrated_on_disk(cfg))

    hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=_spy_sleep,
        rng=random.Random(0),
    )

    # Before post 6 (5 done) and post 11 (10 done) the earlier posts are already on disk.
    assert seen_on_disk[4] == 5 and seen_on_disk[9] == 10
    assert _hydrated_on_disk(cfg) == 12


def test_sigterm_mid_run_persists_progress_and_restores_the_handler(tmp_path: Path) -> None:
    import os
    import signal

    # A harmless stand-in for the default disposition, so a missing handler fails the
    # test instead of killing pytest.
    previous = lambda *_a: None  # noqa: E731
    original = signal.signal(signal.SIGTERM, previous)
    try:
        cfg = _cfg(tmp_path, max_per_run=6)
        page = _many_posts(cfg, 6)
        calls: list[int] = []

        def _kill_on_third(_s: float) -> None:
            calls.append(1)
            if len(calls) == 3:
                os.kill(os.getpid(), signal.SIGTERM)

        with pytest.raises(KeyboardInterrupt):
            hydrate(
                cfg,
                now=_now,
                context_factory=_factory(page),
                sleep=_kill_on_third,
                rng=random.Random(0),
            )

        assert _hydrated_on_disk(cfg) == 3
        assert signal.getsignal(signal.SIGTERM) is previous
    finally:
        signal.signal(signal.SIGTERM, original)


@pytest.mark.parametrize("status", [429, 999])
def test_a_throttle_status_stops_the_run_without_marking_the_post_dead(
    tmp_path: Path, status: int
) -> None:
    cfg = _cfg(tmp_path)
    u1, u2, u3 = _three_posts(cfg)
    page = _FakePage({u1: _page_html(digits="1", body="one")}, statuses={u2: status})

    with pytest.raises(ThrottledError):
        hydrate(
            cfg,
            now=_now,
            context_factory=_factory(page),
            sleep=lambda _s: None,
            rng=random.Random(0),
        )

    assert page.goto_urls == [u1, u2]  # stopped hammering LinkedIn
    stored = load_store(cfg.items_path)
    assert stored["li-1"].text == "one"
    assert stored["li-2"].content is None  # untouched: retried on the next run
    assert stored["li-3"].content is None


def test_a_miss_records_diagnostics_without_page_payloads(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    save_store({"li-1": _stub("1")}, cfg.items_path)
    url = "https://www.linkedin.com/feed/update/urn:li:activity:1"
    page = _FakePage({url: _page_html(digits="999", body="Someone else's secret text")})

    hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=lambda _s: None,
        rng=random.Random(0),
    )

    error = load_store(cfg.items_path)["li-1"].content.sources[0].error or ""
    assert "identity:mismatch" in error and "999" in error
    assert "wanted=1" in error and "container=yes" in error
    assert "secret text" not in error


def test_a_miss_on_a_page_without_the_container_records_its_title(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    save_store({"li-1": _stub("1")}, cfg.items_path)
    url = "https://www.linkedin.com/feed/update/urn:li:activity:1"
    page = _FakePage({url: "<html><head><title>Sign In | LinkedIn</title></head></html>"})

    hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=lambda _s: None,
        rng=random.Random(0),
    )

    error = load_store(cfg.items_path)["li-1"].content.sources[0].error or ""
    assert "container=no" in error and "Sign In | LinkedIn" in error


def test_a_removed_post_notice_without_the_container_is_a_terminal_not_found(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    save_store({"li-1": _stub("1")}, cfg.items_path)
    url = "https://www.linkedin.com/feed/update/urn:li:activity:1"
    page = _FakePage({url: deleted_page()})  # HTTP 200, like the real removed-post page

    hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=lambda _s: None,
        rng=random.Random(0),
    )

    stored = load_store(cfg.items_path)
    assert stored["li-1"].content.sources[0].failure_reason == "not_found"
    assert items_needing_hydration(stored, force=False) == []
    assert "container=no" in (stored["li-1"].content.sources[0].error or "")


def test_a_truncated_body_is_a_transient_failure_with_the_reason(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    save_store({"li-1": _stub("1")}, cfg.items_path)
    url = "https://www.linkedin.com/feed/update/urn:li:activity:1"
    page = _FakePage({url: post_page("1", truncated=True)})

    hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=lambda _s: None,
        rng=random.Random(0),
    )

    stored = load_store(cfg.items_path)
    source = stored["li-1"].content.sources[0]
    assert source.failure_reason == "unknown_error" and "truncated_body" in (source.error or "")
    assert stored["li-1"].text == ""  # a fragment is never stored as the post


def test_a_200_page_without_update_is_a_transient_failure_not_a_dead_post(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    save_store({"li-1": _stub("1")}, cfg.items_path)
    page = _FakePage({})  # soft authwall / captcha: 200 but no Update

    hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=lambda _s: None,
        rng=random.Random(0),
    )

    stored = load_store(cfg.items_path)
    failure = stored["li-1"].content.sources[0]
    assert failure.failure_reason == "unknown_error" and failure.attempts == 1
    assert [i.id for i in items_needing_hydration(stored, force=False)] == ["li-1"]


def test_transient_failures_stop_being_retried_after_three_attempts() -> None:
    def failed(attempts: int) -> Content:
        return Content(
            fetched_at=_NOW,
            sources=[
                ContentSourceFailure(
                    kind="li_post",
                    url="https://x.test",
                    failure_reason="unknown_error",
                    attempts=attempts,
                )
            ],
        )

    store = {"li-1": _stub("1", content=failed(2)), "li-2": _stub("2", content=failed(3))}
    assert [i.id for i in items_needing_hydration(store, force=False)] == ["li-1"]
    assert len(items_needing_hydration(store, force=True)) == 2


def test_five_consecutive_misses_stop_the_run_as_probably_blocked(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, max_per_run=10)
    save_store({f"li-{n}": _stub(str(n), age_days=n) for n in range(1, 9)}, cfg.items_path)
    page = _FakePage({})  # every page is a 200 with no Update

    with pytest.raises(ThrottledError):
        hydrate(
            cfg,
            now=_now,
            context_factory=_factory(page),
            sleep=lambda _s: None,
            rng=random.Random(0),
        )

    assert len(page.goto_urls) == 5
    stored = load_store(cfg.items_path)
    assert sum(1 for i in stored.values() if i.content is not None) == 5


def test_missing_linkedin_session_fails_before_any_snapshot(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    save_store({"li-1": _stub("1")}, cfg.items_path)

    with pytest.raises(FileNotFoundError, match="socialbrain-li login"):
        hydrate(cfg, now=_now)  # real factory: no auth/linkedin_storage_state.json

    assert not (cfg.data_dir / "snapshots").exists()


@pytest.mark.parametrize("limit", [0, -1])
def test_non_positive_limit_is_rejected(tmp_path: Path, limit: int) -> None:
    cfg = _cfg(tmp_path)
    save_store({"li-1": _stub("1")}, cfg.items_path)

    with pytest.raises(ValueError, match="--limit"):
        hydrate(cfg, limit=limit, dry_run=True, now=_now)


def test_force_selection_goes_least_recently_hydrated_first() -> None:
    def hydrated_at(days_ago: int) -> Content:
        return Content(fetched_at=_NOW - timedelta(days=days_ago), sources=[])

    store = {
        "li-new": _stub("new", age_days=1, content=hydrated_at(0)),  # hydrated today
        "li-old": _stub("old", age_days=50, content=hydrated_at(9)),  # hydrated long ago
        "li-fresh": _stub("fresh", age_days=40),  # never attempted
    }

    forced = [i.id for i in items_needing_hydration(store, force=True)]

    assert forced == ["li-fresh", "li-old", "li-new"]


def test_work_saved_by_another_command_during_the_run_is_not_lost(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    u1, u2, u3 = _three_posts(cfg)
    # a 4th stub beyond the 3-post cap: not part of this run's batch
    store = load_store(cfg.items_path)
    store["li-4"] = _stub("4", age_days=4)
    save_store(store, cfg.items_path)

    class _ConcurrentWriter(_FakePage):
        """Another command rewrites items.json while the browser loop is running."""

        def _do_goto(self, url: str) -> None:
            if url == u2:
                other = load_store(cfg.items_path)
                other["li-4"].text = "edited by another command"
                other["tw-1"] = Item(
                    id="tw-1",
                    source="bookmark",
                    url="https://x.com/a/status/1",
                    author=Author(handle="a", name="A"),
                    text="added meanwhile",
                    created_at=_NOW,
                    captured_at=_NOW,
                )
                save_store(other, cfg.items_path)
            super()._do_goto(url)

    page = _ConcurrentWriter({u1: _page_html(digits="1", body="one")})

    hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=lambda _s: None,
        rng=random.Random(0),
    )

    stored = load_store(cfg.items_path)
    assert stored["li-1"].text == "one"  # this run's work
    assert stored["tw-1"].text == "added meanwhile"  # the other command's item
    assert stored["li-4"].text == "edited by another command"  # ...and its edit


def test_logged_out_landing_stops_the_run_and_keeps_partial_progress(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    save_store(
        {
            "li-1": _stub("1", age_days=1),
            "li-2": _stub("2", age_days=2),
            "li-3": _stub("3", age_days=3),
        },
        cfg.items_path,
    )
    url1 = "https://www.linkedin.com/feed/update/urn:li:activity:1"
    url2 = "https://www.linkedin.com/feed/update/urn:li:activity:2"
    # li-1 hydrates; li-2's navigation lands on the authwall.
    page = _FakePage(
        {url1: _page_html(digits="1", body="First body")},
        landed={url2: "https://www.linkedin.com/authwall"},
    )

    with pytest.raises(SessionExpiredError):
        hydrate(
            cfg,
            now=_now,
            context_factory=_factory(page),
            sleep=lambda _s: None,
            rng=random.Random(0),
        )

    assert page.goto_urls == [url1, url2]  # stopped at the post that hit the wall
    stored = load_store(cfg.items_path)
    assert stored["li-1"].text == "First body"  # hydrated before the wall — persisted
    assert stored["li-2"].content is None  # the offending post is untouched, not failed
    assert stored["li-3"].content is None  # never reached
    assert cfg.state_path.exists()  # the run happened; last_run is recorded


def test_max_per_run_cap_from_config_is_respected(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)  # max_per_run = 3
    save_store({f"li-{n}": _stub(str(n), age_days=n) for n in range(10)}, cfg.items_path)
    page = _FakePage({})

    report = hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=lambda _s: None,
        rng=random.Random(0),
    )

    assert report.selected == 3
    assert len(page.goto_urls) == 3


def test_delay_is_drawn_from_config_bounds(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    save_store({f"li-{n}": _stub(str(n), age_days=n) for n in range(3)}, cfg.items_path)
    page = _FakePage({})
    slept: list[float] = []

    hydrate(
        cfg,
        now=_now,
        context_factory=_factory(page),
        sleep=slept.append,
        rng=random.Random(0),
    )

    assert len(slept) == 2  # one between each pair, none after the last
    assert all(cfg.linkedin_min_delay_s <= s <= cfg.linkedin_max_delay_s for s in slept)


def test_nothing_to_hydrate_is_a_clean_noop(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    save_store({"li-1": _stub("1", content=Content(fetched_at=_NOW, sources=[]))}, cfg.items_path)

    report = hydrate(cfg, now=_now, context_factory=_factory(_FakePage({})))

    assert report == HydrateReport()
    assert not (cfg.data_dir / "snapshots").exists()


def test_module_exposes_settle_budget() -> None:
    assert hydrate_mod._SETTLE_MS == 6000
