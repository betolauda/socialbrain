# UPSTREAM_SYNC.md — cherry-pick ledger

Every commit pulled from `upstream/develop` (or another upstream branch),
and every commit deliberately **not** pulled, gets one row here. See
[`docs/FORK.md`](FORK.md) for the sync playbook. Skipping a commit is
normal — silently skipping one is how a fork rots without anyone noticing.

Fork base: this fork branched from `VGonPa/xbrain@main` at commit
`546ed6b` (`Merge pull request #73 from VGonPa/develop`), 2026-09-05.

## Picked

| Date | Upstream SHA | Summary | Notes |
|---|---|---|---|
| — | — | — | (none yet) |

## Skipped

| Date | Upstream SHA | Summary | Reason |
|---|---|---|---|
| — | — | — | (none yet) |

## Bugs found in upstream (report back, or fix locally and note it)

| Date | File | What | Status |
|---|---|---|---|
| 2026-09-05 | `.github/workflows/quality.yml` | CI's install step used `uv pip install -e ".[dev]"`, which ignores the committed `uv.lock` and re-resolves every dependency fresh from PyPI on every run. Ruff/mypy have both shipped new rules/behavior since the lock was cut, so a from-scratch CI run fails on lint drift unrelated to any real change (confirmed: PR0, a docs-only rename, failed CI on a pre-existing `UP017` violation in `archive.py` that the pinned `ruff==0.15.13` from the lock does not flag). **Fixed in this fork** (PR0) by switching to `uv sync --extra dev --locked`, which fails loudly on lock drift instead of silently masking it. Worth reporting upstream — it will bite `VGonPa/xbrain`'s own CI the same way whenever a fresh runner resolves a newer tool version. |

## Watching

Branches not yet on `develop` that are likely to matter for this fork's
seams (`item.id`, `item.source`, `State`, `generate.py`, `ContentKind`):

| Branch | Why it matters |
|---|---|
| `upstream/VGonPa/knowledge-index-02-6a2a-item-fingerprints` | Almost certainly fingerprints `(item.id, item.source, ...)` — the two fields this fork's `SourceName`/id-namespacing widen. See `docs/FORK.md`. |
| `upstream/VGonPa/umbrella-knowledge-index-lexical` | Umbrella branch for the whole knowledge-index series; check its child branches as they merge. |
