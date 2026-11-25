from __future__ import annotations

from pathlib import Path

import pytest

from common import uniquename

STAMP = "20261125T045639Z"


def test_three_calls_in_one_second_get_separate_directories(tmp_path: Path) -> None:
    got = [uniquename.make_unique_dir(tmp_path / "p", STAMP).name for _ in range(3)]
    assert got == [STAMP, f"{STAMP}-001", f"{STAMP}-002"]
    assert all((tmp_path / "p" / n).is_dir() for n in got)


def test_three_calls_in_one_second_get_separate_files_and_nothing_is_overwritten(tmp_path: Path) -> None:
    folder = tmp_path / "failed"
    paths = []
    for i in range(3):
        path, handle = uniquename.create_unique_file(folder, STAMP)
        with handle:
            handle.write(f"report {i}")
        paths.append(path)
    assert [p.name for p in paths] == [f"{STAMP}.json", f"{STAMP}-001.json", f"{STAMP}-002.json"]
    assert [p.read_text() for p in paths] == ["report 0", "report 1", "report 2"]


def test_an_existing_file_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / f"{STAMP}.json").write_text("old")
    path, handle = uniquename.create_unique_file(tmp_path, STAMP)
    handle.close()
    assert path.name == f"{STAMP}-001.json"
    assert (tmp_path / f"{STAMP}.json").read_text() == "old"


def test_an_existing_directory_and_its_content_are_left_alone(tmp_path: Path) -> None:
    (tmp_path / STAMP).mkdir()
    (tmp_path / STAMP / "keep").write_text("x")
    assert uniquename.make_unique_dir(tmp_path, STAMP).name == f"{STAMP}-001"
    assert (tmp_path / STAMP / "keep").read_text() == "x"


def test_new_second_gets_the_plain_name(tmp_path: Path) -> None:
    uniquename.make_unique_dir(tmp_path, STAMP)
    assert uniquename.make_unique_dir(tmp_path, "20261125T045640Z").name == "20261125T045640Z"


def test_exhausted_suffixes_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uniquename, "MAX_SUFFIX", 3)
    for _ in range(4):
        uniquename.make_unique_dir(tmp_path, STAMP)
    with pytest.raises(uniquename.NameExhaustedError):
        uniquename.make_unique_dir(tmp_path, STAMP)
    for _ in range(4):
        uniquename.create_unique_file(tmp_path / "f", STAMP)[1].close()
    with pytest.raises(uniquename.NameExhaustedError):
        uniquename.create_unique_file(tmp_path / "f", STAMP)
