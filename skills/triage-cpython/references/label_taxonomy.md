# CPython label taxonomy

Copy label names exactly. Area labels have no prefix: write `stdlib`, never `area-stdlib`.
Definitions are quoted from the CPython devguide (devguide.python.org/triage/labels).

## Type labels: exactly one

| label | devguide definition | counter-examples |
|---|---|---|
| `type-bug` | "unexpected behaviors, bugs, or exceptions (not hard crashes)" | A Python traceback is a bug, not a crash. A regression between versions is a bug. |
| `type-crash` | "hard crashes of the interpreter, possibly with a core dump" | Segfault, abort, `Fatal Python error`, a failed C `assert` in a debug build. An uncaught `RecursionError` or `MemoryError` is *not* a crash. |
| `type-feature` | "feature requests or enhancements" | New parameters, new functions, changed defaults, new warnings, speed-ups that change no behaviour are usually `type-feature` + `performance`. |
| `type-refactor` | "general code refactoring that does not change user-facing behaviour" | Cleanups, removing dead code, converting to Argument Clinic, modernising internals. |
| `type-security` | "security issues" | Denial of service through crafted input, path traversal, unsafe defaults. Vulnerabilities themselves go to the Python Security Response Team, so public issues are usually hardening. |

In the training data, bugs outnumber features about 2:1, and crashes are about 1 in 7 bugs.

## Area labels: where the fix goes

| label | devguide definition |
|---|---|
| `stdlib` | "standard library modules in the Lib directory (written in Python)" |
| `extension-modules` | "standard library modules in the Modules directory (written in C)" |
| `interpreter-core` | "the interpreter core in the Objects, Python, Grammar, and Parser dirs (written mostly in C)" |
| `docs` | "documentation in the Doc directory (written in reStructuredText), docstrings, and code comments" |
| `tests` | "tests in the Lib/test directory (written in Python) and other changes related to tests" |
| `build` | the build process and cross-builds (configure, Makefiles, PCbuild, platform build scripts) |
| `infra` | "infrastructure of the project (for example, GitHub Actions, dependabot, the buildbots)" |
| `performance` | performance or resource usage; combined with a type label (usually `type-feature` or `type-bug`) and another area |

Common confusions:
- Built-in types (`list`, `dict`, `str`, `int`, `object`), the compiler, the bytecode interpreter, the parser, the import system core and the GC are `interpreter-core`, even when the report shows only Python code.
- A module with a C accelerator (`_json`, `_pickle`, `_datetime`, `_decimal`, `_io`, `_asyncio`, `_ssl`, `_sqlite`, `_ctypes`) is `extension-modules` when the bug is in the C code, `stdlib` when it is in the pure-Python part.
- A flaky or failing test is `tests`, and usually `type-bug`; a docs typo is `docs` and usually `type-bug` or `type-feature` (new docs).

## Topic and OS labels: only when clearly applicable

Topic labels notify the relevant experts. Add one when the issue is squarely about that
topic, not when it is merely mentioned. The allowed list is given in the task; the
frequent ones are:
`topic-JIT`, `topic-C-API`, `topic-repl`, `topic-free-threading`, `topic-asyncio`,
`topic-typing`, `topic-profiling`, `topic-subinterpreters`, `topic-multiprocessing`,
`topic-XML`, `topic-parser`, `topic-importlib`, `topic-email`, `topic-tkinter`,
`topic-SSL`, `topic-sqlite3`, `topic-ctypes`.

- `topic-free-threading`: the free-threaded (no-GIL, `3.13t`/`3.14t`) build, data races, TSan reports.
- `topic-repl`: the interactive shell (`python` with no arguments, `_pyrepl`), not IDLE (`topic-IDLE`).
- `topic-C-API`: the public or internal C API (`Include/`, `PyObject_*` functions), usually from extension authors.

OS labels (`OS-windows`, `OS-mac`, `OS-linux`, `OS-android`, `OS-ios`, `OS-wasi`,
`OS-emscripten`, `OS-unsupported`) are for problems specific to that platform, not for
every report that happens to mention the reporter's OS.
