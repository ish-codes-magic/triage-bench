# Label taxonomy

Use only the labels below. The supplied descriptions and examples guide classification; examples are illustrative, not additional rules. A label needs evidence in the issue or investigation. More than one label may apply when it captures a distinct supported dimension.

## Type

- `type-bug` — Unexpected behavior, bug, or error. Counterexample: a request for new behavior without a claim that existing behavior is wrong.
- `type-crash` — A hard interpreter crash, possibly with a core dump. Counterexample: an exception, test failure, or incorrect result without a hard crash.
- `type-feature` — A feature request or enhancement. Counterexample: a report that existing behavior is unexpectedly broken.
- `type-refactor` — Code refactoring with no behavior change. Counterexample: a request to change observable behavior.
- `type-security` — A security issue. Do not infer security significance merely from a failure or performance problem.

## Component area

Choose based on the likely fix location; see [component_map.md](component_map.md).

- `stdlib` — Standard Library Python modules in `Lib/`.
- `extension-modules` — C modules in `Modules/`.
- `interpreter-core` — `Objects/`, `Python/`, `Grammar/`, and `Parser/`.
- `docs` — Documentation in `Doc/`.
- `tests` — Tests in `Lib/test/`.
- `build` — Build process and cross-build.
- `infra` — CI, GitHub Actions, buildbots, Dependabot, and related infrastructure.

## Other supplied labels

- `performance` — Performance or resource usage. Counterexample: an ordinary correctness report without a performance or resource concern.
- `OS-android`, `OS-emscripten`, `OS-ios`, `OS-linux`, `OS-mac`, `OS-unsupported`, `OS-wasi`, `OS-windows` — Platform labels. The supplied list gives no formal definitions; use one only when the issue identifies that platform as relevant. Do not infer a platform from the component alone.
- `topic-C-API`, `topic-IDLE`, `topic-IO`, `topic-JIT`, `topic-SSL`, `topic-XML`, `topic-argument-clinic`, `topic-asyncio`, `topic-ctypes`, `topic-dataclasses`, `topic-email`, `topic-ensurepip`, `topic-free-threading`, `topic-importlib`, `topic-installation`, `topic-lazy-imports`, `topic-multiprocessing`, `topic-parser`, `topic-pathlib`, `topic-profiling`, `topic-regex`, `topic-repl`, `topic-sqlite3`, `topic-subinterpreters`, `topic-tkinter`, `topic-typing`, `topic-unicode`, `topic-venv` — Subject-area labels. Use only when the issue concerns that named area; a related example or overlapping component alone does not establish a topic label. `topic-repl` is related to the interactive shell; `topic-venv` is related to the venv module.

Do not create a duplicate, information-request, severity, or other label unless it appears in this allowed vocabulary.
