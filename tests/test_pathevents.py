import pytest

from mytools.pathevents import FileChanges


def test_subunsub(tmp_path) -> None:
    path = tmp_path / "file"
    expected = "value"
    fc = FileChanges[str]()
    unwatch = fc.watch(path, expected)
    with pytest.raises(ValueError):
        fc.watch(path, "other")
    fc.start()
    path.write_text("some text")
    assert next(fc.fetch_paths()) == expected
    unwatch()
    fc.shutdown()
    assert fc.files == {}
