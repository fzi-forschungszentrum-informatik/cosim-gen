"""project.py's pure-config helpers: the extra_files basename-collision guard. No build
deps - pure Python."""

import pytest

from cosim.project import _reject_basename_collisions


def test_basename_collision_rejected(tmp_path):
    a = tmp_path / "a" / "bootrom.mem"
    a.parent.mkdir()
    a.write_text("one")
    b = tmp_path / "b" / "bootrom.mem"
    b.parent.mkdir()
    b.write_text("two")
    with pytest.raises(RuntimeError) as exc_info:
        _reject_basename_collisions([a, b])
    assert "bootrom.mem" in str(exc_info.value)


def test_same_file_listed_twice_is_fine(tmp_path):
    f = tmp_path / "bootrom.mem"
    f.write_text("one")
    _reject_basename_collisions([f, f])


def test_no_collision_is_fine(tmp_path):
    a = tmp_path / "a.mem"
    b = tmp_path / "b.mem"
    a.write_text("one")
    b.write_text("two")
    _reject_basename_collisions([a, b])
