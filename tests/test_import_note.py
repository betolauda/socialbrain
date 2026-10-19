# tests/test_import_note.py
import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from xbrain.cli import app
from xbrain.models import Author, Item, MediaVideoPending, VideoFrame
from xbrain.store import load_store, save_store

runner = CliRunner()


def _setup_repo(tmp_path: Path, monkeypatch) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        f'vault = "{vault}"\n'
        'output_subdir = "x-knowledge"\n'
        'data_dir = "data"\n'
        "[x]\n"
        'handle = "vgonpa"\n',
        encoding="utf-8",
    )
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("XBRAIN_REPO_ROOT", str(tmp_path))
    return tmp_path / "data" / "items.json"


def _item(item_id: str, *, video: bool = True) -> Item:
    item = Item(
        id=item_id,
        source="bookmark",
        url=f"https://x.com/a/status/{item_id}",
        author=Author(handle="alice", name="Alice"),
        text=f"Note {item_id}",
        created_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        captured_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )
    if video:
        item.media = [
            MediaVideoPending(
                url="https://video.twimg.com/amplify_video/900/vid/720/a.mp4?tag=16",
                thumbnail_url="https://pbs.twimg.com/p.jpg",
                bitrate=2_176_000,
                duration_millis=30_000,
            )
        ]
    return item


def _write_transcript(path: Path, **overrides) -> Path:
    data = {
        "text": "Hola mundo",
        "language": "es",
        "has_speech": True,
        "segments": [{"start": 0.0, "end": 2.5, "text": "Hola mundo"}],
        "title": "Charla",
        "source": "a.mp4",
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_import_note_attaches_x_video_source(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    transcript = _write_transcript(tmp_path / "transcript.json")

    result = runner.invoke(app, ["import-note", str(transcript), "--item", "42"])

    assert result.exit_code == 0, result.output
    source = load_store(items_path)["42"].content.sources[0]
    assert source.kind == "x_video"
    assert source.text == "Hola mundo"
    assert source.language == "es"
    assert source.title == "Charla"
    assert source.has_speech is True


def test_import_note_repeated_item_attaches_to_all(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"1": _item("1"), "2": _item("2")}, items_path)
    transcript = _write_transcript(tmp_path / "transcript.json")

    result = runner.invoke(app, ["import-note", str(transcript), "--item", "1", "--item", "2"])

    assert result.exit_code == 0, result.output
    store = load_store(items_path)
    assert store["1"].content.sources[0].kind == "x_video"
    assert store["2"].content.sources[0].kind == "x_video"


def test_import_note_unknown_item_fails_cleanly_and_writes_nothing(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"1": _item("1")}, items_path)
    transcript = _write_transcript(tmp_path / "transcript.json")

    result = runner.invoke(app, ["import-note", str(transcript), "--item", "1", "--item", "999"])

    assert result.exit_code == 1
    assert "999" in result.output
    assert load_store(items_path)["1"].content is None


def test_import_note_no_speech_is_attached_as_data(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    transcript = _write_transcript(
        tmp_path / "transcript.json", text="", has_speech=False, segments=[]
    )

    result = runner.invoke(app, ["import-note", str(transcript), "--item", "42"])

    assert result.exit_code == 0, result.output
    source = load_store(items_path)["42"].content.sources[0]
    assert source.kind == "x_video"
    assert source.has_speech is False
    assert source.text == ""


def test_import_note_skips_item_with_existing_transcript_unless_force(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    first = _write_transcript(tmp_path / "v1.json", text="v1")
    second = _write_transcript(tmp_path / "v2.json", text="v2")
    runner.invoke(app, ["import-note", str(first), "--item", "42"])

    skipped = runner.invoke(app, ["import-note", str(second), "--item", "42"])
    assert skipped.exit_code == 0, skipped.output
    assert load_store(items_path)["42"].content.sources[0].text == "v1"

    forced = runner.invoke(app, ["import-note", str(second), "--item", "42", "--force"])
    assert forced.exit_code == 0, forced.output
    sources = load_store(items_path)["42"].content.sources
    assert [s.kind for s in sources] == ["x_video"]
    assert sources[0].text == "v2"


def test_import_note_snapshots_before_writing(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    transcript = _write_transcript(tmp_path / "transcript.json")

    result = runner.invoke(app, ["import-note", str(transcript), "--item", "42"])

    assert result.exit_code == 0, result.output
    assert "Snapshot created" in result.output


def test_import_note_malformed_json_fails_cleanly(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")

    result = runner.invoke(app, ["import-note", str(bad), "--item", "42"])

    assert result.exit_code == 1
    assert load_store(items_path)["42"].content is None


def test_import_note_missing_file_fails_cleanly(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)

    result = runner.invoke(app, ["import-note", str(tmp_path / "nope.json"), "--item", "42"])

    assert result.exit_code == 1


def test_import_note_rejects_json_without_text_or_segments(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    alien = tmp_path / "alien.json"
    alien.write_text(json.dumps({"words": [{"w": "hola"}]}), encoding="utf-8")

    result = runner.invoke(app, ["import-note", str(alien), "--item", "42"])

    assert result.exit_code == 1
    assert "text" in result.output and "segments" in result.output
    assert load_store(items_path)["42"].content is None


def test_import_note_force_with_alien_json_keeps_real_transcript(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    real = _write_transcript(tmp_path / "real.json", text="real")
    runner.invoke(app, ["import-note", str(real), "--item", "42"])
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["import-note", str(empty), "--item", "42", "--force"])

    assert result.exit_code == 1
    assert load_store(items_path)["42"].content.sources[0].text == "real"


def test_import_note_accepts_segments_only_no_speech(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    only_segments = tmp_path / "s.json"
    only_segments.write_text(json.dumps({"segments": [], "has_speech": False}), encoding="utf-8")

    result = runner.invoke(app, ["import-note", str(only_segments), "--item", "42"])

    assert result.exit_code == 0, result.output
    assert load_store(items_path)["42"].content.sources[0].has_speech is False


def test_import_note_rejects_item_without_video(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"1": _item("1"), "2": _item("2", video=False)}, items_path)
    transcript = _write_transcript(tmp_path / "transcript.json")

    result = runner.invoke(app, ["import-note", str(transcript), "--item", "1", "--item", "2"])

    assert result.exit_code == 1
    assert "2" in result.output and "video" in result.output.lower()
    store = load_store(items_path)
    assert store["1"].content is None and store["2"].content is None


def test_import_note_force_keeps_prior_slides(tmp_path: Path, monkeypatch):
    from xbrain.digest import attach_transcript
    from xbrain.transcribe import Transcript

    items_path = _setup_repo(tmp_path, monkeypatch)
    store = {"42": _item("42")}
    frame = VideoFrame(timestamp=3.0, local_path="42/frames/1.png", description="slide")
    attach_transcript(
        store, ["42"], Transcript(text="old", has_speech=True), frames_by_item={"42": [frame]}
    )
    save_store(store, items_path)
    new = _write_transcript(tmp_path / "new.json", text="new")

    result = runner.invoke(app, ["import-note", str(new), "--item", "42", "--force"])

    assert result.exit_code == 0, result.output
    source = load_store(items_path)["42"].content.sources[0]
    assert source.text == "new"
    assert [f.local_path for f in source.frames] == ["42/frames/1.png"]


def test_import_note_unknown_item_message_has_no_repr_quotes(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"1": _item("1")}, items_path)
    transcript = _write_transcript(tmp_path / "transcript.json")

    result = runner.invoke(app, ["import-note", str(transcript), "--item", "999"])

    assert result.exit_code == 1
    assert "Error: item(s) not found" in result.output


def test_import_note_all_skipped_says_nothing_written_and_hints_force(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    transcript = _write_transcript(tmp_path / "transcript.json")
    runner.invoke(app, ["import-note", str(transcript), "--item", "42"])

    result = runner.invoke(app, ["import-note", str(transcript), "--item", "42"])

    assert result.exit_code == 0, result.output
    assert "--force" in result.output
    assert "no se escribió nada" in result.output
    assert "Snapshot created" not in result.output


def test_import_note_drops_the_title_of_a_silent_transcript(tmp_path: Path, monkeypatch):
    """video2note titles a no-speech video with a generic placeholder; as the note title it
    would hide the tweet's own text. A spoken transcript keeps its title."""
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"1": _item("1"), "2": _item("2")}, items_path)
    silent = _write_transcript(
        tmp_path / "silent.json",
        text="",
        segments=[],
        has_speech=False,
        title="Video sin transcripcion ni texto en pantalla",
    )
    spoken = _write_transcript(tmp_path / "spoken.json", title="Charla")

    assert runner.invoke(app, ["import-note", str(silent), "--item", "1"]).exit_code == 0
    assert runner.invoke(app, ["import-note", str(spoken), "--item", "2"]).exit_code == 0

    store = load_store(items_path)
    assert store["1"].content.sources[0].title is None
    assert store["2"].content.sources[0].title == "Charla"
