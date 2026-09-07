# LINKEDIN_CAPTURE.md — human-navigated capture of LinkedIn saved posts

> **SUPERSEDED — 2026-09-07.** Part 2 of the data archive shipped
> `Saved_Items_<member>.csv`: 751 rows, `savedItem,CreatedTime`, zero
> duplicates. The export path is alive, so this contingency is **not needed**
> and must not be implemented. It is kept only for its decision record — if
> LinkedIn ever drops the file, start here.
>
> Measured facts that retire this design's open questions: the corpus is **751
> items** (open question 4 — manual scrolling was never going to be reasonable
> at that size), and both timestamps are recoverable from the CSV alone
> (questions 2 and 3), so the tier-2 DOM fallback was never the weak link it
> looked like.

**Status: contingency design, not yet implemented.** This is the fallback for
PR4's acquisition input if LinkedIn's data export turns out not to ship a
`Saved Items` file. Read `docs/FORK.md` first — the divergence discipline and
the LinkedIn risk posture it sets are the constraints this design answers to.

## Why this exists

The planned PR4 input is the `Saved Items` file from LinkedIn's official data
export: two columns, saved date and post URL. LinkedIn's help centre documents
it as part of the ~48h full archive.

Measured on a real account (2026-09-06):

| Surface | Result |
|---|---|
| Granular file picker | 5 options only — `Saved Items` absent |
| Part 1 of the archive ("Basic", 31 files) | `Saved Items` absent; the four `Saved*` files are all jobs-related |
| Part 2 of the archive (~24h) | **pending — decides whether this document is needed** |

If part 2 ships `Saved Items`, implement PR4 against the CSV and discard this
design. If it does not, the export path is dead and this is the replacement.

## The design in one sentence

Open a real browser with the user's LinkedIn session, navigate to the saved-posts
page, **hand the human the controls**, passively record the Voyager responses
LinkedIn sends to their screen as they scroll by hand, and parse those into
`li_saved` stubs when they say they're done.

## What makes it different from scraping

The distinction is narrow and worth stating precisely, because the entire risk
justification rests on it.

| | Automated scroll | **This design** |
|---|---|---|
| Who navigates | The script | The human |
| Who scrolls | `page.mouse.wheel` in a loop | The human's hands |
| Request pacing | Script-timed | Human reading speed |
| What the tool does | Drives the session | Observes the session |
| Traffic shape to LinkedIn | Paginated burst | An ordinary browsing session |

The automation opens a window and listens. It does not decide what to fetch,
when to fetch it, or how far to go. That is a materially different access
pattern from the one LinkedIn's User Agreement targets, and a materially
different fingerprint to its anti-abuse systems.

**This is a risk reduction, not a risk elimination.** Playwright is still an
automation framework and this is still a grey area against the User Agreement.
Anyone implementing this should hold that honestly rather than treat the
distinction as a licence.

### Volume comparison with the already-accepted `hydrate`

Worth recording because it inverts the intuition:

- One capture session: roughly 20–40 Voyager responses for hundreds of items.
- `hydrate` over 500 posts: 500 page loads at 45–120 s each — around 10 hours
  of automated navigation.

Capture is by a wide margin the *lighter* of the two. If `hydrate` clears the
fork's risk bar, capture clears it comfortably.

## Core divergence: zero

Every file below is new, under `src/xbrain/linkedin/`. No core file is touched,
so this adds nothing to the cherry-pick cost tracked in `FORK.md`.

```
src/xbrain/linkedin/__init__.py
src/xbrain/linkedin/urn.py       # URN → item id
src/xbrain/linkedin/parse.py     # Voyager / DOM payload → Item stubs
src/xbrain/linkedin/capture.py   # the session: navigate, yield, listen, collect
src/xbrain/linkedin/cli.py       # socialbrain-li app
tests/test_linkedin_urn.py
tests/test_linkedin_parse.py
tests/test_linkedin_capture.py
```

`pyproject.toml` gains the already-reserved console script (see the comment at
`pyproject.toml:23`):

```toml
socialbrain-li = "xbrain.linkedin.cli:app"
```

### Browser context: reuse `x_context` as-is

`extract.browser.x_context` already takes `storage_state_path` as a parameter
and is X-specific in name only — the X-specific pieces (`X_LOGIN_URL`,
`is_logged_out`) live outside it. Import it directly:

```python
from xbrain.extract.browser import x_context  # generic despite the name
```

Rationale: widening or renaming it would touch a core file for zero functional
gain, which is exactly what `FORK.md` forbids. The misnomer is the cheaper cost.
Record the reason in the importing module's docstring so a future reader does
not "fix" it.

The LinkedIn session lives at the path already declared in
`platforms.PLATFORMS["linkedin"].auth_filename` → `linkedin_storage_state.json`.
It does not exist yet; `socialbrain-li login` (mirroring `browser.login`) creates it.

## Flow

```
socialbrain-li capture
  │
  ├─ 1. resolve auth/linkedin_storage_state.json    → missing? tell the user to run `login`
  ├─ 2. x_context(..., headless=False)              → headful, always
  ├─ 3. page.on("response", collector)              → REGISTERED BEFORE NAVIGATION
  ├─ 4. page.goto(SAVED_POSTS_URL)
  │
  ├─ 5. ┌─────────────────────────────────────────────────┐
  │     │  print: "Scroll through your saved posts by     │
  │     │  hand until you reach the end, then press       │
  │     │  Enter here."                                   │
  │     │  input()          ← blocks on the human         │
  │     └─────────────────────────────────────────────────┘
  │
  ├─ 6. parse collected payloads → Item stubs (dedup by URN)
  ├─ 7. merge_items(store, items)   → never overwrites (store.py:29)
  └─ 8. save store + state.li_saved_imported
```

Step 5 is the whole design. There is no scroll loop, no idle counter, no
timing heuristic — the three things `extract/extractor.py` needs and this
deliberately does not.

`SAVED_POSTS_URL = "https://www.linkedin.com/my-items/saved-posts/"`

## Parsing: two tiers, degrading into the CSV shape

Mirror the anchoring discipline of `extract/graphql.py` — key names and shapes,
never paths. Per `FORK.md`, LinkedIn's Voyager surface uses **pinned queryIds**,
so `ARCHITECTURE.md` invariant #7 does not transfer. Match the coarse substring
`/voyager/api/` and never a pinned id.

**Tier 1 — Voyager interception (rich).** Voyager returns `included: [...]`
arrays with `$type` discriminators. Walk them for entities carrying a
`urn:li:activity:<id>` or `urn:li:ugcPost:<id>` plus an author. Yields id, url,
author, text, timestamp.

**Tier 2 — DOM harvest (minimal, fallback).** If tier 1 yields nothing — the
API drifted, or the page went server-rendered — read the rendered DOM for
anchors matching `/feed/update/urn:li:activity:...`. Yields id and url only.

Tier 2's output is *exactly* the two columns the `Saved Items` CSV would have
given us. The fallback degrades into the shape PR4 was designed around, which
is the property that makes this design safe to build before the export question
is settled: if part 2 of the archive ships the CSV tomorrow, the tier-2 parser
and the stub builder are still the code you want.

### Stub shape

`platforms.is_hydrated` (`platforms.py:104`) gates on `links or media or
enriched`, so a stub with none of those is correctly invisible to `fetch` and
`generate` until `hydrate` fills it in.

| Field | Tier 1 | Tier 2 |
|---|---|---|
| `id` | `li-<activity_id>` (prefix from `platforms.py:58`) | same |
| `source` | `"li_saved"` | same |
| `url` | `https://www.linkedin.com/feed/update/urn:li:activity:<id>/` | same |
| `author` | from payload | `Author(handle="", name="")` placeholder |
| `text` | post text | `""` |
| `created_at` | from payload | **open question — see below** |
| `captured_at` | now | now |

## Guardrails

1. **No automated scrolling, ever.** Pin it with a test that greps
   `capture.py` for `mouse.wheel`, `scroll_into_view`, `keyboard.press("End")`.
   If that call ever appears, the entire risk justification above collapses
   silently — so make it fail loudly instead.
2. **Headful only.** No `--headless` flag on this command. A human has to be
   there; offering the flag contradicts the premise.
3. **Never persist raw Voyager payloads.** They carry third parties' personal
   data. Parse in memory, discard. No debug dump, no fixture recorded from a
   live capture.
4. **No `[linkedin]` delay config here.** Those guardrails pace *automated*
   requests; this command issues none. Note it explicitly so nobody "fixes"
   the omission.
5. **Idempotent by construction.** `merge_items` never overwrites, so re-running
   after a partial scroll is additive and safe. No cursor logic needed.

## Testing

Per the repo convention (`CLAUDE.md`), every module gets `tests/test_*.py`.

- Pure-function tests on `collect_saved_items(responses) -> list[Item]`,
  mirroring `extractor.collect_new_items` — no browser in the test path.
- Dedup: the same URN across several payloads yields one item.
- Tier fallback: tier-1-empty input falls through to the DOM parser.
- The no-auto-scroll guard test from guardrail 1.
- Malformed/partial payloads are skipped, never raise.

**Fixtures must be constructed, not recorded** — both for the privacy reason in
guardrail 3 and to match how the X Article work was fixtured. That means they
are *unvalidated against production* until someone runs a real capture, exactly
the caveat `FORK.md` carries for `#39 PR2/PR3`. Say so in the test module
docstring.

## Open questions — resolve against a real capture before trusting this

1. **Does the saved-posts page actually call `/voyager/api/` on scroll?** The
   whole tier-1 path assumes infinite scroll backed by Voyager. Unverified.
   If the page is server-rendered, tier 2 carries the feature alone.
2. **`created_at` in tier 2.** The DOM gives no reliable post timestamp. Options:
   fall back to `captured_at` (wrong but harmless — nothing in the pipeline
   filters `li_saved` by date), or leave hydration to correct it. Decide when
   the data is in front of you, not now.
3. **Saved date is lost.** The CSV would have carried it; capture probably will
   not. Nothing in the current pipeline reads it, so this is likely a non-issue —
   confirm before discarding.
4. **Volume.** How many saved posts are there? If it is thousands, manual
   scrolling stops being reasonable and the tradeoff needs revisiting.

## Decision record

Rejected alternatives, so they are not re-litigated:

- **Automated Playwright scroll (the original proposal).** Same data, materially
  worse access pattern, contradicts the posture set in `FORK.md`. Rejected on
  risk profile, not on effort.
- **Manual URL list.** Zero risk, does not scale past a handful. Fine as an
  escape hatch, not as the feature.
- **Third-party exporter extensions.** Hands the entire saved corpus to an
  unrelated vendor. Rejected on privacy.
- **Abandon the backlog, capture forward-only.** Loses the corpus that motivated
  the fork.
