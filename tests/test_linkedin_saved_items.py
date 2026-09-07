"""Tests for `xbrain.linkedin.saved_items` — export CSV/ZIP -> li_saved Item stubs.

Every fixture here is constructed inline. The real export under
``linkedin_data/`` is personal data and is never read, copied, or referenced.
"""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path

from xbrain.linkedin.saved_items import parse_saved_items
from xbrain.linkedin.urn import post_timestamp
from xbrain.platforms import is_hydrated

_ACTIVITY_URN_ID = "7495649402552913920"
_ARTICLE_URN_ID = "7215433500339197848"
_ACTIVITY_URL = f"https://www.linkedin.com/feed/update/urn:li:activity:{_ACTIVITY_URN_ID}"
_ARTICLE_URL = f"https://www.linkedin.com/feed/update/urn:li:article:{_ARTICLE_URN_ID}"


def _csv(*rows: str) -> str:
    return "savedItem,CreatedTime\n" + "\n".join(rows) + "\n"


def _write_csv(tmp_path: Path, body: str, name: str = "Saved_Items_123.csv") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_activity_row_uses_urn_timestamp_not_created_time(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, _csv(f"{_ACTIVITY_URL},2026-08-19 01:25:29"))
    items = parse_saved_items(path)
    assert len(items) == 1
    item = items[0]
    assert item.id == f"li-{_ACTIVITY_URN_ID}"
    assert item.source == "li_saved"
    assert item.url == _ACTIVITY_URL
    assert item.author.handle == "" and item.author.name == ""
    assert item.text == ""
    # created_at comes from the URN, which predates the save timestamp.
    assert item.created_at == post_timestamp("activity", _ACTIVITY_URN_ID)
    assert item.created_at < datetime(2026, 8, 19, 1, 25, 29, tzinfo=timezone.utc)


def test_stub_item_is_not_hydrated(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, _csv(f"{_ACTIVITY_URL},2026-08-19 01:25:29"))
    (item,) = parse_saved_items(path)
    assert not is_hydrated(item)
    assert item.created_at.tzinfo is not None
    assert item.captured_at.tzinfo is not None


def test_article_row_falls_back_to_created_time(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, _csv(f"{_ARTICLE_URL},2017-03-31 20:50:25"))
    (item,) = parse_saved_items(path)
    assert item.id == f"li-{_ARTICLE_URN_ID}"
    assert item.created_at == datetime(2017, 3, 31, 20, 50, 25, tzinfo=timezone.utc)


def test_reads_csv_straight_out_of_zip(tmp_path: Path) -> None:
    zip_path = tmp_path / "Complete_LinkedInDataExport.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("Saved_Items_123.csv", _csv(f"{_ACTIVITY_URL},2026-08-19 01:25:29"))
    (item,) = parse_saved_items(zip_path)
    assert item.id == f"li-{_ACTIVITY_URN_ID}"


def test_saved_items_member_found_at_any_depth(tmp_path: Path) -> None:
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "nested/dir/saved_items_999.CSV", _csv(f"{_ACTIVITY_URL},2026-08-19 01:25:29")
        )
    assert len(parse_saved_items(zip_path)) == 1


def test_zip_decoy_members_are_never_read(tmp_path: Path, monkeypatch) -> None:
    """The private members in the same export must never be read off the ZIP."""
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("Saved_Items_123.csv", _csv(f"{_ACTIVITY_URL},2026-08-19 01:25:29"))
        archive.writestr("messages.csv", "GARBAGE PRIVATE DATA")
        archive.writestr("Connections.csv", "GARBAGE PRIVATE DATA")
        archive.writestr("Email Addresses.csv", "GARBAGE PRIVATE DATA")

    read_members: list[str] = []
    original_read = zipfile.ZipFile.read

    def _spy_read(self, name, pwd=None):
        read_members.append(name if isinstance(name, str) else name.filename)
        return original_read(self, name, pwd)

    monkeypatch.setattr(zipfile.ZipFile, "read", _spy_read)
    parse_saved_items(zip_path)
    assert read_members == ["Saved_Items_123.csv"]


def test_missing_saved_items_member_raises_clear_error(tmp_path: Path) -> None:
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("messages.csv", "x")
    try:
        parse_saved_items(zip_path)
    except ValueError as exc:
        assert "saved_items*.csv" in str(exc).lower()
    else:  # pragma: no cover - the call must raise
        raise AssertionError("expected a ValueError for a missing saved-items member")


def test_duplicate_ids_deduped_first_wins(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path,
        _csv(
            f"{_ACTIVITY_URL},2026-08-19 01:25:29",
            f"{_ACTIVITY_URL},2026-09-01 12:00:00",
        ),
    )
    items = parse_saved_items(path)
    assert len(items) == 1


def test_malformed_rows_skipped_without_raising(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path,
        _csv(
            ",2026-08-19 01:25:29",
            "https://example.com/not-linkedin,2026-08-19 01:25:29",
            f"{_ARTICLE_URL},not-a-date",
            f"{_ACTIVITY_URL},2026-08-19 01:25:29",
        ),
    )
    items = parse_saved_items(path)
    assert [item.id for item in items] == [f"li-{_ACTIVITY_URN_ID}"]


def test_empty_export_returns_empty_list(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "savedItem,CreatedTime\n")
    assert parse_saved_items(path) == []
