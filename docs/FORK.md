# FORK.md — why this fork exists and how it stays maintainable

## What this is

`socialbrain` is a public fork of [`xbrain`](https://github.com/VGonPa/xbrain)
(Víctor González Pacheco, MIT), extended to support a second source —
LinkedIn saved posts — alongside the original X/Twitter support, sharing one
JSON store, one Obsidian vault, and one topic taxonomy across both.

It is a fork, not a contribution back upstream. `xbrain`'s own
`CONTRIBUTING.md` states: *"XBrain reads X through X's internal endpoints,
for personal use, with your own account and your own data. Keep
contributions within that scope."* A second platform falls outside that
scope by the maintainer's own words, so this was never proposed upstream —
it was forked instead, which the MIT license explicitly permits.

## The one rule that matters: minimize core divergence

`xbrain` upstream is under active development (a `develop` branch, an
in-flight `knowledge-index` series with an umbrella PR, frequent merges).
Every line this fork changes in a **core** (source-agnostic) file is a line
that can conflict with a future `git cherry-pick` from upstream. The
guiding constraint on every change here is:

> Prefer additive changes (new literals, new appended fields, new files) over
> restructuring. Where a seam must be opened in an existing file, make it the
> smallest change that could plausibly be upstreamed on its own.

Target: **under ~80 changed lines across the whole source-agnostic core**,
excluding the dashboard (see below). Track the actual number here as PRs
land:

| PR | Core files touched | Δ lines (core only) |
|---|---|---|
| 0 | docs, `pyproject.toml`, `.github/workflows/quality.yml` | branding + a pre-existing CI reproducibility bug fix, not counted |
| 1 | `models.py` (+35/-4), `cli.py` (+9/-2 incl. import), `generate.py` (+1/-1) | **~39 net** |
| 2 | `config.py`, `cli.py` | _pending_ |
| 3 | `generate.py`, `rubrics.py` + 3 rubric `.md` | _pending_ |
| 7 | `media.py`, `fetch.py` | _pending_ |
| 8 | `dashboard.py` + `resources/dashboard.template.html` | _pending, deliberately last_ |

PRs 4, 5, 6 (the LinkedIn acquisition layer, session handling, and hydrator)
are purely additive — new files under `src/xbrain/linkedin/` — and are not
in this table because they touch zero core files.

## Why the importable package is still `xbrain`

Only the **distribution name**, **console scripts**, and **documentation**
are rebranded to `socialbrain`. `src/xbrain/` and every `from xbrain...
import ...` line stay byte-identical to upstream.

Renaming the Python package namespace would be purely cosmetic — the
namespace is an implementation detail, invisible to the CLI user — and it
would make **every future upstream commit that touches an import block**
conflict, since `git`'s default diff context (3 lines) means an import
header is exactly where renames collide hardest. Upstream's in-flight
`knowledge-index` series alone is adding ~7 new modules, each with its own
import header. Renaming the package now would front-load that pain forever.

If upstream ever goes dormant and this fork's own identity matters more
than sync-ability, the rename is a single mechanical PR at that point —
cheap precisely because nothing else was ever coupled to the package name.

## Console scripts

```toml
[project.scripts]
socialbrain    = "xbrain.cli:app"           # X CLI — unchanged module
xbrain         = "xbrain.cli:app"           # retained alias for muscle memory / upstream docs
socialbrain-li = "xbrain.linkedin.cli:app"  # LinkedIn CLI — new module (added with the linkedin/ package)
```

## Documented escape hatch: `State` as a keyed map

`models.State` gained one named field (`li_saved: SourceCursor`) rather than
being refactored to `cursors: dict[str, SourceCursor]`. The named field is a
4-line, purely-additive diff; the keyed-map refactor would touch `State`'s
body, `cli._run_extract`, and `cli.status` — all high-traffic upstream
files — for a benefit (scaling past 2 sources) this fork doesn't need yet.

**If a third source is ever added**, migrate then, with this shim (do not
build it preemptively):

```python
def _promote_legacy_state(value: Any) -> Any:
    """Promote the pre-migration per-source named fields into the keyed map."""
    if not isinstance(value, dict) or "cursors" in value:
        return value
    legacy = {"bookmarks": "bookmark", "own_tweets": "own_tweet", "li_saved": "li_saved"}
    cursors = {new: value[old] for old, new in legacy.items() if old in value}
    return {k: v for k, v in value.items() if k not in legacy} | {"cursors": cursors}

State = Annotated[_State, BeforeValidator(_promote_legacy_state)]
```

## An invariant upstream states that this fork cannot honor

`ARCHITECTURE.md` invariant #7 says: *"Operation names, not query ids — the
extractor anchors to X GraphQL operation names because X rotates the ids."*
LinkedIn's internal Voyager API has been migrating onto a GraphQL surface
with **pinned `queryId`s** — the opposite stability profile. The LinkedIn
hydrator's Voyager tier is therefore explicitly **opportunistic** (matches
the coarse substring `/voyager/api/`, never a pinned id) and is the
*secondary*, not primary, extraction path — see `docs/tutorial.md` /
`src/xbrain/linkedin/parse.py` docstrings for the tiering. Anyone reading
the upstream invariants list should not assume #7 holds for the LinkedIn
side of this fork.

## Sync playbook

```bash
git remote add upstream https://github.com/VGonPa/xbrain.git   # already done
git fetch upstream
git log --oneline main..upstream/develop -- src/xbrain          # source commits only
git cherry-pick -x <sha>                                        # -x records the origin sha
uv run poe check                                                 # after EVERY pick
```

Log every pick — and every deliberate skip, with a one-line reason — in
[`docs/UPSTREAM_SYNC.md`](UPSTREAM_SYNC.md). A skipped commit is normal; a
silently skipped commit is how a fork quietly rots.

**Watch `upstream/VGonPa/knowledge-index-02-6a2a-item-fingerprints`
specifically** — it fingerprints items and will very likely key on
`item.id` and `item.source`, the two fields this fork widens. The widening
is only in the *value space* (`li-<digits>` is still a `str`; `li_saved` is
still a `Literal` member), so a fingerprint over `(id, source, text, …)`
should keep working — but verify when that branch lands on `develop`, and
cherry-pick it early rather than letting divergence stack.

## Dashboard: take-upstream-wholesale policy

`src/xbrain/resources/dashboard.template.html` is a single-file HTML
artifact with inline ECharts JS — the highest-conflict file in the repo.
On every upstream template change:

```bash
git checkout upstream/develop -- src/xbrain/resources/dashboard.template.html
# then re-apply this fork's documented patch (data-driven source pie,
# LinkedIn host exclusion, per-platform KPI labels) by hand
```

Do not attempt a line-level merge on this file.
