"""Tests for `xbrain.linkedin.hydrate` — selection/resume + the browser loop.

The loop is exercised with a fake Playwright context/page (no browser, no
network, no real delays). Every HTML fixture is constructed inline from the
reconnaissance *shape* — nothing from `linkedin_data/`.
"""

from __future__ import annotations

import html
import json
import random
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from xbrain.config import load_config
from xbrain.linkedin import hydrate as hydrate_mod
from xbrain.linkedin.hydrate import (
    HydrateReport,
    SessionExpiredError,
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
    envelope = {
        "included": [
            {
                "entityUrn": f"urn:li:fsd_update:(urn:li:activity:{digits},FEED_DETAIL)",
                "$type": "com.linkedin.voyager.dash.feed.Update",
                "commentary": {"text": {"text": body}},
                "actor": None,
                "content": {"imageComponent": {"images": []}},
            }
        ]
    }
    escaped = html.escape(json.dumps(envelope))
    return f'<code style="display: none" id="bpr-guid-1">{escaped}</code>'


class _FakePage:
    def __init__(self, htmls: dict[str, str], landed: dict[str, str] | None = None) -> None:
        self._htmls = htmls
        self._landed = landed or {}
        self._current = ""
        self.url = ""
        self.goto_urls: list[str] = []

    def goto(self, url: str, wait_until: str | None = None) -> None:
        self.goto_urls.append(url)
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


def _cfg(tmp_path: Path):
    (tmp_path / "vault").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "config.toml").write_text(
        f'[paths]\nvault = "{tmp_path / "vault"}"\noutput_subdir = "k"\ndata_dir = "data"\n'
        "[linkedin]\nmax_per_run = 3\nmin_delay_s = 20\nmax_delay_s = 20\n",
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


def test_parse_miss_records_a_not_found_failure(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    save_store({"li-1": _stub("1")}, cfg.items_path)
    page = _FakePage({})  # every URL returns the "nothing here" default

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
