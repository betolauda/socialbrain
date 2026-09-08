# LINKEDIN_HYDRATE.md — PR6 spec: hydrating LinkedIn saved posts

**Status: spec, not yet implemented.** Designed against a real reconnaissance
capture of 7 saved posts (2026-09-07), not against assumptions — see
*Reconnaissance* below. Read `docs/FORK.md` first for the divergence discipline
and the LinkedIn risk posture this answers to.

PR4 imports `Saved_Items*.csv` into 751 empty `li_saved` stubs. PR5 adds the
session. This is the step that fills the stubs in.

## Reconnaissance: what a LinkedIn post page actually serves

Seven saved items were captured with a headful browser and a live session
(1 text+image post, 4 random `activity` posts, 2 `article` items).

**The post is not delivered by an XHR.** Across 35 intercepted
`/voyager/api/` responses on the first capture, **none** carried the post —
they were comments, social counts, notifications, presence. The post model is
server-side-rendered into the initial HTML inside
`<code style="display:none" id="bpr-guid-NNNNNN">` blocks (LinkedIn's BigPipe
rendering), as standard Voyager JSON: `{data, meta, included}`.

This is *better* than the interception design assumed. No scroll triggers, no
lazy-load timing, no race. `goto` → settle → `page.content()` → parse.

### The shape, measured

Each capture had ~9 `bpr-guid` blocks; exactly one carried a
`com.linkedin.voyager.dash.feed.Update` in its `included`. Merging the
`included` arrays of every block gives ~104 entities keyed by `entityUrn`.

**Fields prefixed with `*` are URN references**, not inline data — they
resolve against that merged pool (standard Voyager denormalisation). E.g.
`linkedInVideoComponent["*videoPlayMetadata"] = "urn:li:digitalmediaAsset:…"`
resolves to a `VideoPlayMetadata` entity elsewhere in `included`.

| Path on `Update` | Seen in | Content |
|---|---|---|
| `commentary.text.text` | 6/7 | Post body, plain text with `\n`. `commentary.text.attributes[]` carries mentions/hashtags/links as `{start, length, …}` ranges — empty in all 7 samples, but the field exists. |
| `actor.name.text` | activity posts | Display name (`"Ruben Hassid"`). Empty on `articleComponent` items. |
| `actor.navigationContext.actionTarget` | activity posts | `https://www.linkedin.com/in/<handle>?…` → the handle. |
| `content.imageComponent.images[]` | 4/7 | **1 to 7 images** (a "carousel" is just multi-image, not a separate component). Each: `detailData.vectorImage.rootUrl` + `artifacts[]` (6 widths; `fileIdentifyingUrlPathSegment` is a signed path, `expiresAt` ≈ 2027). Full URL = `rootUrl + fileIdentifyingUrlPathSegment`. `accessibilityText` is generic boilerplate ("Ver imagen", "Shared from Hypefury") — not real alt text. |
| `content.linkedInVideoComponent` | 1/7 | `*videoPlayMetadata` → `VideoPlayMetadata`: `progressiveStreams[].streamingLocations[].url` (signed mp4), `adaptiveStreams` (HLS), `thumbnail`, `duration` (ms), `aspectRatio`. |
| `content.articleComponent` (`type: "EXTERNAL_FULL"`) | 2/7 | **An external link share, not a native article.** `navigationContext.actionTarget` is the real external URL; `title` / `subtitle` (domain) / `description`. `commentary` and `actor` are both empty. |
| `entityUrn` | all | `urn:li:fsd_update:(urn:li:activity:<ID>,FEED_DETAIL,…)` — carries the id, so a parsed page can be matched back to its stub. |

**Not yet seen** (7 samples is not the corpus): `documentComponent` (PDF /
slides), `resharedUpdate` (repost), polls, celebrations. `content` is a union
of ~30 nullable components; at most one is non-null per post.

## The design

```
socialbrain-li hydrate [--limit N] [--force] [--dry-run]
  │
  ├─ auto-snapshot data/  (mutates items in place — mirrors refresh-media)
  ├─ select stubs needing hydration (see Resume, below)
  ├─ x_context(storage_state_for("linkedin"), headless=False)
  │
  └─ for each item, up to cfg.linkedin_max_per_run:
       ├─ page.goto(item.url); settle
       ├─ is_logged_out(page.url)?  → STOP the loop; persist what hydrated; raise (session died, not a 404)
       ├─ html = page.content()
       ├─ update = bpr.find_update(html)          ← pure
       ├─ apply post.map_update(update) onto the item   ← pure
       └─ sleep(random(min_delay_s, max_delay_s))
```

### Files (all new — zero core divergence)

```
src/xbrain/linkedin/bpr.py       HTML → merged Voyager entity pool + `*` resolution   PURE
src/xbrain/linkedin/post.py      Update entity → (text, author, media, links)          PURE
src/xbrain/linkedin/hydrate.py   the browser loop, pacing, guardrails, store writes
src/xbrain/linkedin/cli.py       + the `hydrate` command                              (edit)
tests/test_linkedin_bpr.py
tests/test_linkedin_post.py
tests/test_linkedin_hydrate.py
```

The `bpr.py` / `post.py` split is deliberate: **everything that can be wrong is
pure and testable without a browser.** The browser shell is a thin loop with no
parsing logic in it.

## The rendering trap — and what it settles

`generate._render_note` renders **both**:

```python
lines += [f"## {platform.post_heading}", "", item.text, ""]   # generate.py:589
...
if item.content:
    lines += _content_lines(item.content, strings)             # generate.py:600
```

So writing the body into `item.text` **and** into a
`ContentSourceSuccess(kind="li_post", text=body)` prints it **twice** in the
note. And `ContentSourceSuccess.text` is required — an "empty success" source
is not constructible by design.

**Decision: the body lives in `item.text`.** Not in a content source.

This is also what PR3 already built for: `platform_strings` gives LinkedIn its
own `post_heading`, so the body renders under a LinkedIn-native heading via
`item.text`. It is additionally what `_render_log` (`generate.py:716`) and the
index snippet read.

`kind="li_post"` is therefore used **only for the failure variant** — structured
evidence that hydration was attempted and could not get a body. That is a real
use, consistent with the "broken links are demonstrable, not assumed" rule, and
it leaves `ContentKind`'s `li_post` literal (added in PR1) meaningful.

### What gets written

| Case | Effect on the stub |
|---|---|
| **Activity post** | `text` ← `commentary.text.text`; `author` ← `Author(handle, name)`; `media` ← `MediaPhotoPending[]` (images) or `MediaVideoPending` (video); `links` ← hyperlink attributes in the body; `content` ← `Content(fetched_at=now, sources=[])` |
| **`EXTERNAL_FULL` article** | `links` ← `[Link(actionTarget)]`; `text` ← title + description; `content` ← `Content(fetched_at=now, sources=[])`. The **existing** `fetch` stage then pulls the real page via trafilatura/firecrawl as an `external_article` — no LinkedIn-specific code for the body. |
| **Unrecognised component** | `text` ← `commentary.text.text` if present; media skipped; logged at WARNING. **Never a failure.** |
| **Post deleted / inaccessible** | `content` ← `Content(fetched_at=now, sources=[ContentSourceFailure(kind="li_post", url, failure_reason="not_found")])` |

`Content(sources=[])` on success is not a placeholder — it is the bookkeeping
record: `fetched_at` gives the resume check, the re-enrichment trigger, and an
"attempted at T" timestamp, for free and with no duplicate rendering.

**Reuse, not reinvention:** `MediaPhotoPending` means `xbrain media` downloads
LinkedIn images with the existing engine, size cascade, failure classification
and `_media/` vault mirroring — zero new plumbing. `MediaVideoPending` is
constructed directly from `VideoPlayMetadata` (**not** via
`extract.video.build_video_media`, whose input shape is X's
`video_info.variants` dict).

### Visibility: hydrated ≠ visible

`platforms.is_hydrated` and `generate._has_note` both gate on
`links or media or enriched` — **not on `text`.** A hydrated text-only post
with no images and no links stays note-less until `enrich` runs. The real
pipeline is:

```
import → hydrate → enrich → topics → generate
```

This is not worth a core change to `_has_note`; `enrich` runs anyway.

## Resume and idempotency — the central requirement, not a nicety

751 posts at 45–120 s is **~17 hours**, or **31 runs** at the default
`max_per_run=25` (~34 min each). The hydrator is not a command you run once; it
is something you run over weeks. Every run must know exactly where it left off
**from the store alone**, with no side state.

Selection mirrors `fetch._should_refetch`:

- `content is None` → hydrate (never attempted).
- `--force` → hydrate regardless.
- A recorded `li_post` failure whose reason is transient (`timeout`,
  `dns_error`, `unknown_error`) → retry automatically.
- A terminal failure (`not_found`, `forbidden`) → skip unless `--force`.
- Otherwise → skip (already hydrated).

Newest-first ordering: recent posts are likelier to still exist.

## Guardrails

1. **Pacing from config, never hardcoded** — `linkedin_min_delay_s` /
   `linkedin_max_delay_s` / `linkedin_max_per_run` (PR2, validated: delays
   ≥ 20 s, cap ≤ 100). Random uniform delay between posts.
2. **Headful only.** No `--headless` flag. A human is meant to be around.
3. **A logged-out landing stops the run — keeping partial progress.**
   `is_logged_out` (PR5) covers `/login`, `/authwall`, `/checkpoint/`,
   `/uas/login`, `/m/login`. The loop stops at the post that hit the wall;
   posts hydrated before it are persisted (a run spans 31 sessions — a mid-run
   authwall must not discard ~25 completed posts), then `SessionExpiredError`
   is raised. The offending post is left untouched, **never recorded as a
   per-post failure** — marking a live post dead because of an unrelated
   session problem is the single worst failure mode in this design.
4. **Auto-snapshot before the first write** (mirrors `refresh-media`,
   `digest-video`). A snapshot that cannot be taken aborts the run.
5. **One bad post never aborts the batch** — a parse miss is a logged failure
   on that item; the loop continues.
6. **Never persist raw BPR payloads.** They carry other people's comments,
   profiles and PII. Parse in memory, keep only the mapped fields.

## Testing

Repo convention: every module gets `tests/test_*.py`.

- `bpr.py`: block extraction from constructed HTML, HTML-entity unescaping,
  merging `included` across blocks, `*`-reference resolution, a block that is
  not JSON (skipped, never raises), no `Update` present (returns `None`).
- `post.py`: text extraction; author handle parsed out of the profile URL;
  1-image and 7-image posts; a video post resolving `*videoPlayMetadata` to the
  highest-bitrate mp4; `EXTERNAL_FULL` yielding a `Link` and no `li_post`
  source; an unknown component degrading to text-only; a missing `commentary`.
- `hydrate.py`: selection/resume logic (pure, no browser) — transient retried,
  terminal skipped, `--force` overriding; `max_per_run` respected; a
  logged-out landing stopping the loop, persisting the posts hydrated before it,
  leaving the offending post untouched, and re-raising; delays drawn from config
  bounds.

**Fixtures are constructed inline, from the *shapes* recorded during
reconnaissance — never copied from `linkedin_data/`,** which holds real
personal data of third parties (guardrail 6). Note the honest consequence,
the same caveat `FORK.md` carries for `#39 PR2/PR3`: constructed fixtures are
not a production guarantee. Unlike that work, the shapes here were read off a
real capture first.

## Open questions

1. **Unseen components.** `documentComponent`, `resharedUpdate`, polls. The
   degrade-to-text fallback covers them safely, but a repost's body may live on
   the *reshared* update rather than the outer one — worth a targeted recon
   before assuming text-only is right for those.
2. **Signed media URLs expire** (`expiresAt` ≈ 2027 in the samples). If
   `xbrain media` runs long after `hydrate`, a URL may be dead. Options: run
   `media` promptly after each hydrate batch, or store `expiresAt` and re-hydrate
   on expiry. Not solved here.
3. **Video scope.** `MediaVideoPending` makes LinkedIn videos eligible for
   `download-videos` and, in principle, `digest-video` transcription. Whether to
   wire that up is deliberately out of scope for PR6.
4. **`commentary.text.attributes` was empty in all 7 samples.** The
   link/mention extraction path is therefore designed but unexercised. Treat it
   as unvalidated until a post with inline links is parsed.
