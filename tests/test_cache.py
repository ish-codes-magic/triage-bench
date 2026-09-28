from pathlib import Path

from triagelab.cache import DiskCache


def test_miss_then_hit(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    assert cache.get("ab" * 32) is None
    cache.put("ab" * 32, {"text": "hello", "n": 1})
    assert cache.get("ab" * 32) == {"text": "hello", "n": 1}


def test_entries_fan_out_by_key_prefix(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    cache.put("cd1234", {"x": 1})
    assert (tmp_path / "cd" / "cd1234.json").is_file()


def test_corrupt_entry_is_a_miss(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    (tmp_path / "ef").mkdir()
    (tmp_path / "ef" / "ef99.json").write_text("{not json", encoding="utf-8")
    assert cache.get("ef99") is None


def test_no_temp_files_left_behind(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    cache.put("aa01", {"x": 1})
    assert not list(tmp_path.rglob("*.tmp"))
