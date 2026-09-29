# CPython component map

The component is the directory a fix would change. The first matching row wins, so
`Lib/test/` is `tests` even though it is under `Lib/`. This table mirrors
`configs/repos/python__cpython.yaml` (a test keeps them in sync).

| component | directories |
|---|---|
| `tests` | `Lib/test/` |
| `docs` | `Doc/` |
| `stdlib` | `Lib/` |
| `extension-modules` | `Modules/` |
| `interpreter-core` | `Objects/`, `Python/`, `Grammar/`, `Parser/`, `Include/` |
| `build` | `PCbuild/`, `Tools/build/`, `Tools/wasm/`, `Android/`, `iOS/`, `Mac/`, `configure`, `Makefile.pre.in`, `pyconfig.h.in` |
| `infra` | `.github/`, `.azure-pipelines/` |

In the training data the most common components are `interpreter-core` and `stdlib`
(27% each), then `extension-modules` (16%) and `docs` (15%).

## Finding the directory

- `search_code` with the function or class name from the traceback. A hit in
  `Lib/foo.py` means `stdlib`; `Modules/_foomodule.c` means `extension-modules`.
- Many modules exist twice: a Python module in `Lib/` and a C accelerator in `Modules/`
  (`json`/`_json`, `pickle`/`_pickle`, `datetime`/`_datetime`, `asyncio`/`_asynciomodule.c`,
  `io`/`_io`, `decimal`/`_decimal`). A C-level crash or a wrong result only with the C
  version points to `Modules/`.
- Built-in types and functions live in `Objects/` (`listobject.c`, `dictobject.c`,
  `unicodeobject.c`, `longobject.c`) and `Python/bltinmodule.c`: `interpreter-core`.
- Syntax errors, the tokenizer and the grammar: `Parser/` and `Grammar/`. The compiler,
  bytecode, `ceval`, the JIT and the specializer: `Python/`. Both are `interpreter-core`.
- `get_codeowners` on a path lists its experts, useful for `suggested_owners`.

If a fix would touch several directories, choose the one holding the actual behaviour
change; tests and docs usually change alongside it and are not the component.
