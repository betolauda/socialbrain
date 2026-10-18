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

from dataclasses import dataclass, field
from pathlib import Path

from xbrain.digest import _has_x_video_source, attach_transcript
from xbrain.models import Item
from xbrain.transcribe import Transcript, parse_transcript


@dataclass
class ImportReport:
    """Outcome of an `import_note` run: ids that got the source vs. were skipped."""

    attached: list[str] = field(default_factory=list)
    already: list[str] = field(default_factory=list)


def load_transcript(path: Path) -> Transcript:
    """Read and parse a transcript JSON file; errors surface as clean operator errors."""
    return parse_transcript(Path(path).read_text(encoding="utf-8"))


def import_note(
    store: dict[str, Item],
    item_ids: list[str],
    transcript: Transcript,
    *,
    force: bool = False,
) -> ImportReport:
    """Attach `transcript` to each of `item_ids`.

    Validates every id BEFORE touching anything: an unknown id raises `KeyError`
    and nothing is attached. Items already carrying an `x_video` source are
    skipped unless `force`.
    """
    unknown = [item_id for item_id in item_ids if item_id not in store]
    if unknown:
        raise KeyError(f"item(s) not found in items.json: {', '.join(unknown)}")
    report = ImportReport()
    for item_id in dict.fromkeys(item_ids):
        if not force and _has_x_video_source(store[item_id]):
            report.already.append(item_id)
        else:
            report.attached.append(item_id)
    attach_transcript(store, report.attached, transcript)
    return report
