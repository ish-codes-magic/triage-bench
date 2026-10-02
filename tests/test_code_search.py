import shutil
from pathlib import Path

import pytest

from triagelab.mcp_server.code_search import CodeSearcher


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "Lib" / "asyncio").mkdir(parents=True)
    (tmp_path / "Lib" / "asyncio" / "tasks.py").write_text(
        "def create_task(coro):\n    return Task(coro)\n", encoding="utf-8"
    )
    (tmp_path / "Objects").mkdir()
    (tmp_path / "Objects" / "listobject.c").write_text(
        "int\nPyList_Append(PyObject *op, PyObject *newitem)\n{\n", encoding="utf-8"
    )
    (tmp_path / "blob.bin").write_bytes(b"\0\0PyList_Append\0")
    return tmp_path


BACKENDS = [pytest.param(False, id="python-fallback")]
if shutil.which("rg"):
    BACKENDS.append(pytest.param(True, id="ripgrep"))


@pytest.mark.parametrize("use_rg", BACKENDS)
def test_literal_case_insensitive_search(tree: Path, use_rg: bool) -> None:
    hits, truncated = CodeSearcher(tree, use_ripgrep=use_rg).search("pylist_append")
    assert [(h.path, h.line) for h in hits] == [("Objects/listobject.c", 2)]  # binary skipped
    assert not truncated


@pytest.mark.parametrize("use_rg", BACKENDS)
def test_glob_and_truncation(tree: Path, use_rg: bool) -> None:
    searcher = CodeSearcher(tree, use_ripgrep=use_rg)
    hits, _ = searcher.search("coro", path_glob="Lib/**")
    assert {h.path for h in hits} == {"Lib/asyncio/tasks.py"}
    hits, truncated = searcher.search("coro", max_results=1)
    assert len(hits) == 1
    assert truncated


@pytest.mark.parametrize("use_rg", BACKENDS)
def test_regex_characters_are_literal(tree: Path, use_rg: bool) -> None:
    hits, _ = CodeSearcher(tree, use_ripgrep=use_rg).search("return Task(coro)")
    assert [h.line for h in hits] == [2]


def test_empty_query_finds_nothing(tree: Path) -> None:
    assert CodeSearcher(tree).search("   ") == ([], False)


def test_ripgrep_is_never_picked_up_implicitly(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Search results must not depend on what the machine has installed.
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/rg")
    assert CodeSearcher(tree)._rg is None  # pyright: ignore[reportPrivateUsage]
    assert CodeSearcher(tree, use_ripgrep=True)._rg == "/usr/bin/rg"  # pyright: ignore[reportPrivateUsage]
