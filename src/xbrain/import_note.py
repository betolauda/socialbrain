"""`import-note` — attach an externally produced transcript to stored items.

The counterpart of `digest-video` for transcripts that already exist on disk
(e.g. video2note's `transcript.json`): xbrain does no transcription here, it only
parses the file with the shared transcriber parser and attaches it as an
`x_video` content source via `digest.attach_transcript`, so `enrich → topics →
generate` pick it up unchanged. Items are selected explicitly by id — the origin
URL of a local file is not recoverable, and signed mp4 URLs are unstable.

Mutates the in-memory `store` and returns an `ImportReport`; persisting (with the
destructive auto-snapshot) is the CLI's job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Private on purpose: exposing it would mean editing `digest.py` (core), which the
# fork's divergence rule avoids. If `digest` renames it, this import fails loudly.
from xbrain.digest import _has_x_video_source, attach_transcript
from xbrain.models import ContentSourceSuccess, Item
from xbrain.transcribe import Transcript, parse_transcript
from xbrain.video_fetch import _select_entry


@dataclass
class ImportReport:
    """Outcome of an `import_note` run: ids that got the source vs. were skipped."""

    attached: list[str] = field(default_factory=list)
    already: list[str] = field(default_factory=list)


def load_transcript(path: Path) -> Transcript:
    """Read and parse a transcript JSON file; errors surface as clean operator errors.

    The document must carry `text` or `segments`: a JSON object with neither (the
    wrong file, another tool's schema) would otherwise parse as a valid SILENT
    transcript and, under `--force`, overwrite a real one. An explicit empty
    `text`/`segments` with `has_speech: false` is still a valid no-speech marker.
    """
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None  # let the shared parser raise its own clear error
    if isinstance(data, dict) and "text" not in data and "segments" not in data:
        raise ValueError(
            f"{path}: not a transcript — expected a 'text' and/or 'segments' key "
            f"(found: {', '.join(sorted(data)) or 'none'})"
        )
    return parse_transcript(raw)


def import_note(
    store: dict[str, Item],
    item_ids: list[str],
    transcript: Transcript,
    *,
    force: bool = False,
) -> ImportReport:
    """Attach `transcript` to each of `item_ids`.

    Validates every id BEFORE touching anything: an unknown id, or an item with no
    video media at all, raises `ValueError` and nothing is attached (a typo'd id
    that happens to exist must not get a "Video digest"). Items already carrying
    an `x_video` source are skipped unless `force`; a forced replace keeps the
    prior source's `frames` (slides from `digest-video --frames`).
    """
    unknown = [item_id for item_id in item_ids if item_id not in store]
    if unknown:
        raise ValueError(f"item(s) not found in items.json: {', '.join(unknown)}")
    no_video = [i for i in item_ids if _select_entry(store[i])[1] == "no_video"]
    if no_video:
        raise ValueError(f"item(s) have no video media: {', '.join(no_video)}")
    report = ImportReport()
    for item_id in dict.fromkeys(item_ids):
        if not force and _has_x_video_source(store[item_id]):
            report.already.append(item_id)
        else:
            report.attached.append(item_id)
    frames_by_item = {
        item_id: prior.frames
        for item_id in report.attached
        if (prior := _prior_x_video(store[item_id])) is not None and prior.frames
    }
    attach_transcript(store, report.attached, transcript, frames_by_item=frames_by_item)
    return report


def _prior_x_video(item: Item) -> ContentSourceSuccess | None:
    """The item's current `x_video` source, if it is a success variant."""
    if item.content is None:
        return None
    return next(
        (
            s
            for s in item.content.sources
            if s.kind == "x_video" and isinstance(s, ContentSourceSuccess)
        ),
        None,
    )
