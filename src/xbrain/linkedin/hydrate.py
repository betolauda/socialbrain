"""The LinkedIn hydrator: fill imported ``li_saved`` stubs with real post content.

``socialbrain-li import-saved`` creates empty ``li_saved`` stubs from the data
export. This stage drives a headful browser over the ones that still need
content, parses each post page in memory (`xbrain.linkedin.bpr` +
`xbrain.linkedin.post`), and writes the mapped fields back onto the stub.

Design (docs/LINKEDIN_HYDRATE.md):

- **Resume from the store alone.** 751 posts at 45-120 s is ~17 h; this runs
  over weeks. `items_needing_hydration` mirrors `fetch._should_refetch`: never
  attempted, transient failure, or ``--force`` → hydrate; terminal failure or
  already done → skip.
- **The browser boundary is thin and injectable** (``context_factory``) so the
  loop is testable without Playwright.
- **A logged-out landing stops the run** (`SessionExpiredError`): posts hydrated
  before it are persisted, the offending post is left untouched (not a per-post
  failure, or a live post gets marked dead by an unrelated session problem).
- **Auto-snapshot ``data/`` before the first write**; a snapshot failure aborts
  before any navigation.
- **One bad post never aborts the batch** — a parse miss is a ``not_found``
  failure on that item and the loop continues.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone

import typer
from playwright.sync_api import BrowserContext
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from xbrain import snapshot
from xbrain.config import Config
from xbrain.extract.browser import x_context
from xbrain.linkedin import bpr, post
from xbrain.linkedin.browser import is_logged_out
from xbrain.linkedin.urn import parse_saved_item
from xbrain.models import Content, ContentSourceFailure, FailureReason, Item
from xbrain.store import load_state, load_store, save_state, save_store

logger = logging.getLogger(__name__)

# Settle after `goto` before reading `page.content()` — same budget the X
# modules use (`xbrain.extract.extractor._SETTLE_MS`). The post is already in the
# server-rendered HTML, so this is a load-settle, not a lazy-content wait.
_SETTLE_MS = 6000

# HTTP statuses LinkedIn answers with when it is rate-limiting a scraper. They stop
# the run (never recorded on the post): hammering on only deepens the throttle.
_THROTTLE_STATUSES = frozenset({429, 999})

# Statuses that mean the post is really gone (a terminal ``not_found``).
_GONE_STATUSES = frozenset({404, 410})

# Transient failures are retried at most this many times before they stop being
# selected (``--force`` still re-hydrates them) — otherwise a really-deleted post
# that answers 200 with no Update would eat a slot of every run forever.
_MAX_TRANSIENT_ATTEMPTS = 3

# This many posts in a row failing to yield content (no Update, or a navigation
# error) means LinkedIn is blocking us or the network is down, not that five
# posts were deleted: stop the run instead of marking the queue.
_MAX_CONSECUTIVE_MISSES = 5

# `li_post` failure reasons that justify an automatic retry on the next run —
# mirrors `xbrain.fetch._TRANSIENT_FAILURES`. Everything else (``not_found``,
# ``forbidden``, ...) is terminal: only ``--force`` re-hydrates it.
_TRANSIENT_LI_FAILURES = frozenset({"timeout", "dns_error", "unknown_error"})

ContextFactory = Callable[[], AbstractContextManager[BrowserContext]]


class SessionExpiredError(RuntimeError):
    """A navigation landed on a LinkedIn login / authwall / checkpoint page.

    Raised after the run so the CLI can print a "renew your session" message.
    The loop stops at the post that hit the wall — posts hydrated before it are
    persisted (a run spans many sessions; a mid-run authwall must not throw away
    completed work) — but the offending post is NOT recorded as a failure, or a
    live post would be marked dead by a session problem unrelated to it.
    """


class ThrottledError(RuntimeError):
    """LinkedIn throttled (429/999) or is serving posts without content.

    Like `SessionExpiredError`, raised AFTER the partial progress is persisted;
    the post that triggered a throttle status is left untouched.
    """


@dataclass
class HydrateReport:
    """Counts for the CLI summary line.

    - ``selected``  — stubs chosen for this run (after ``--limit`` and the
      ``linkedin_max_per_run`` cap).
    - ``hydrated``  — stubs a post body / media / link was written onto.
    - ``failed``    — stubs where the page carried no parseable ``Update``
      (recorded as a ``li_post`` ``not_found`` failure).
    - ``dry_run``   — the run only reported its selection.
    - ``stopped``   — why the loop ended early besides a logged-out landing:
      ``"throttled"`` (429/999) or ``"blocked"`` (consecutive content misses).
    - ``session_expired`` — the loop stopped early on a logged-out landing; the
      hydrated/failed counts are the partial progress that was persisted before
      `hydrate` re-raises `SessionExpiredError`.
    """

    selected: int = 0
    hydrated: int = 0
    failed: int = 0
    dry_run: bool = False
    session_expired: bool = False
    stopped: str | None = None


def _utcnow() -> datetime:
    """The default hydrator clock (UTC-aware, injectable for tests)."""
    return datetime.now(timezone.utc)


def _li_post_failures(content: Content) -> list[ContentSourceFailure]:
    """The ``li_post`` failure sources recorded on a content record."""
    return [
        source
        for source in content.sources
        if isinstance(source, ContentSourceFailure) and source.kind == "li_post"
    ]


def _needs_hydration(item: Item, force: bool) -> bool:
    """Whether one ``li_saved`` item should be (re)hydrated this run.

    Mirrors `xbrain.fetch._should_refetch`: never attempted (``content is
    None``) or ``force`` → yes; a transient ``li_post`` failure → yes (auto
    retry); a terminal ``li_post`` failure or an already-hydrated item → no.
    """
    if item.content is None:
        return True
    if force:
        return True
    return any(
        failure.failure_reason in _TRANSIENT_LI_FAILURES
        and failure.attempts < _MAX_TRANSIENT_ATTEMPTS
        for failure in _li_post_failures(item.content)
    )


def items_needing_hydration(store: dict[str, Item], force: bool) -> list[Item]:
    """The ``li_saved`` stubs to hydrate, newest first.

    Newest-first (`created_at` descending): recent posts are likelier to still
    exist. Non-``li_saved`` items are never selected.
    """
    candidates = [
        item
        for item in store.values()
        if item.source == "li_saved" and _needs_hydration(item, force)
    ]
    return sorted(candidates, key=lambda item: item.created_at, reverse=True)


def _apply_post_content(item: Item, content: post.PostContent, now: Callable[[], datetime]) -> None:
    """Write a mapped `PostContent` onto a stub.

    The body lives in ``item.text`` (not a content source — see the
    "rendering trap" in docs/LINKEDIN_HYDRATE.md). ``item.content`` is set to a
    sources-less `Content` purely as the bookkeeping / resume record.
    """
    item.text = content.text
    if content.author is not None:
        item.author = content.author
    item.media = list(content.media)
    item.links = list(content.links)
    item.content = Content(fetched_at=now(), sources=[])


def _record_failure(
    item: Item,
    reason: FailureReason,
    now: Callable[[], datetime],
    *,
    error: str | None = None,
    http_status: int | None = None,
) -> None:
    """Record a ``li_post`` failure on a stub, counting the attempt."""
    prior = _li_post_failures(item.content) if item.content is not None else []
    attempts = max((failure.attempts for failure in prior), default=0) + 1
    item.content = Content(
        fetched_at=now(),
        sources=[
            ContentSourceFailure(
                kind="li_post",
                url=item.url,
                failure_reason=reason,
                error=error,
                http_status=http_status,
                attempts=attempts,
            )
        ],
    )


def _record_parse_miss(item: Item, now: Callable[[], datetime], status: int | None = None) -> None:
    """Record why a page carried no Update for this post.

    Only an explicit 404/410 is the terminal ``not_found``. Anything else (a 200
    soft authwall / captcha, a 5xx, a redirect) is the transient ``unknown_error``
    — retried up to `_MAX_TRANSIENT_ATTEMPTS` times — so a throttling episode
    cannot mark the whole queue permanently dead.
    """
    reason: FailureReason = "not_found" if status in _GONE_STATUSES else "unknown_error"
    _record_failure(item, reason, now, http_status=status)


def _record_navigation_error(item: Item, exc: Exception, now: Callable[[], datetime]) -> None:
    """Record a transient failure for a post whose navigation raised.

    A Playwright timeout is the routine LinkedIn failure; anything else is the
    catch-all. Both are in `_TRANSIENT_LI_FAILURES`, so the next run retries.
    """
    reason: FailureReason = "timeout" if isinstance(exc, PlaywrightTimeout) else "unknown_error"
    _record_failure(item, reason, now, error=str(exc)[:200] or type(exc).__name__)


def _verifiable_urn_id(item: Item) -> str | None:
    """The activity id the parsed Update must belong to; ``None`` when unverifiable.

    ``article`` URNs do not appear in the Update's ``entityUrn``, so they cannot be
    matched (the 2 known cases fall back to the first Update).
    """
    parsed = parse_saved_item(item.url)
    return parsed[1] if parsed is not None and parsed[0] == "activity" else None


def _hydrate_one(
    item: Item, page_html: str, now: Callable[[], datetime], status: int | None = None
) -> bool:
    """Apply one fetched page's HTML onto a stub. Returns ``True`` when hydrated."""
    parsed = bpr.find_update(page_html, urn_id=_verifiable_urn_id(item))
    if parsed is None:
        _record_parse_miss(item, now, status)
        return False
    content = post.map_update(parsed.update, parsed)
    _apply_post_content(item, content, now)
    if content.is_unknown_component:
        logger.warning("LinkedIn post %s hydrated as text-only (unknown component)", item.id)
    return True


def _run_loop(
    items: list[Item],
    context: BrowserContext,
    *,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
    rng: random.Random,
    min_delay: float,
    max_delay: float,
    touched: list[Item],
) -> HydrateReport:
    """Navigate to each item's URL, parse, and apply.

    Stops (does not raise) on a logged-out landing, flagging
    ``report.session_expired`` — the caller persists the partial progress and
    then re-raises `SessionExpiredError`. The post that hit the wall is left
    untouched, not recorded as a failure. A navigation error on one post
    (timeout, closed target) is recorded as a transient failure on THAT post and
    the batch continues. `touched` is filled as the loop goes so the caller can
    persist progress even when the loop is cut short by an exception.
    """
    report = HydrateReport(selected=len(items))
    page = context.new_page()
    misses = 0
    for index, item in enumerate(items):
        if index:
            sleep(rng.uniform(min_delay, max_delay))
        try:
            response = page.goto(item.url, wait_until="domcontentloaded")
            status = getattr(response, "status", None)
            page.wait_for_timeout(_SETTLE_MS)
            landed_url = page.url
            page_html = (
                page.content()
                if not is_logged_out(landed_url) and status not in _THROTTLE_STATUSES
                else ""
            )
        except Exception as exc:  # noqa: BLE001 - one bad post must not abort the batch
            logger.warning("LinkedIn post %s: navigation failed: %s", item.id, exc)
            _record_navigation_error(item, exc, now)
            touched.append(item)
            report.failed += 1
            misses += 1
        else:
            if is_logged_out(landed_url):
                report.session_expired = True
                break
            if status in _THROTTLE_STATUSES:
                report.stopped = "throttled"
                break
            touched.append(item)
            if _hydrate_one(item, page_html, now, status):
                report.hydrated += 1
                misses = 0
            else:
                report.failed += 1
                misses += 1
        if misses >= _MAX_CONSECUTIVE_MISSES:
            report.stopped = "blocked"
            break
    return report


def _select(store: dict[str, Item], *, force: bool, limit: int | None, cap: int) -> list[Item]:
    """Pick the stubs for this run: selection, then ``--limit``, then the run cap."""
    selected = items_needing_hydration(store, force)
    if limit is not None:
        selected = selected[:limit]
    return selected[:cap]


def hydrate(
    cfg: Config,
    *,
    limit: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    now: Callable[[], datetime] = _utcnow,
    context_factory: ContextFactory | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> HydrateReport:
    """Hydrate ``li_saved`` stubs from live LinkedIn post pages.

    Loads the store, selects the stubs needing content (see
    `items_needing_hydration`), snapshots ``data/``, then drives one headful
    browser context over the batch. The store and state are saved after the loop
    — including a loop cut short by a logged-out landing, which persists the
    partial progress and then raises `SessionExpiredError`.

    ``context_factory`` / ``sleep`` / ``rng`` / ``now`` are injected so the loop
    runs under test without Playwright or real delays. ``--dry-run`` reports the
    selection and neither snapshots, navigates, nor writes.
    """
    store = load_store(cfg.items_path)
    state = load_state(cfg.state_path)

    if dry_run:
        selected = _select(store, force=force, limit=limit, cap=cfg.linkedin_max_per_run)
        typer.echo(f"li_saved (dry-run): {len(selected)} stubs a hidratar")
        for item in selected:
            typer.echo(f"  {item.id}  {item.url}")
        return HydrateReport(selected=len(selected), dry_run=True)

    batch = _select(store, force=force, limit=limit, cap=cfg.linkedin_max_per_run)
    if not batch:
        typer.echo("li_saved: 0 stubs a hidratar")
        return HydrateReport()

    path, manifest = snapshot.snapshot_create(
        cfg.data_dir, command="hydrate", dir_label="pre-hydrate"
    )
    typer.echo(f"Snapshot created: {path.name} ({manifest.item_count} items)")

    factory = context_factory or (
        lambda: x_context(cfg.storage_state_for("linkedin"), headless=False)
    )
    touched: list[Item] = []
    report: HydrateReport | None = None
    try:
        with factory() as context:
            report = _run_loop(
                batch,
                context,
                now=now,
                sleep=sleep,
                rng=rng or random.Random(),
                min_delay=cfg.linkedin_min_delay_s,
                max_delay=cfg.linkedin_max_delay_s,
                touched=touched,
            )
    finally:
        # Persist unconditionally — an authwall, a Ctrl-C or an unexpected error
        # part-way still leaves real hydrated posts, and the snapshot was taken.
        if touched or report is not None:
            state.li_saved.last_run = now()
            save_store(store, cfg.items_path)
            save_state(state, cfg.state_path)
    typer.echo(f"li_saved: {report.hydrated} hidratados, {report.failed} fallidos")

    if report.stopped == "throttled":
        raise ThrottledError(
            "LinkedIn está limitando las peticiones (429/999). Espera un buen rato antes de "
            f"reintentar. ({report.hydrated} hidratados antes del corte, guardados)"
        )
    if report.stopped == "blocked":
        raise ThrottledError(
            f"{_MAX_CONSECUTIVE_MISSES} posts seguidos sin contenido: LinkedIn parece estar "
            "bloqueando o sirviendo páginas vacías. Abre un post a mano para comprobarlo y "
            f"reintenta más tarde. ({report.hydrated} hidratados, progreso guardado)"
        )
    if report.session_expired:
        raise SessionExpiredError(
            "La sesión de LinkedIn ha caducado. Ejecuta `socialbrain-li login`. "
            f"({report.hydrated} hidratados antes del corte, guardados)"
        )
    return report
