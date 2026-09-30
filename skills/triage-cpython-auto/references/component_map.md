# Component map

Choose the component by the directory a plausible fix would change, not simply by the user-visible API, issue title, or reported symptom. Use code search to locate the relevant implementation and consult code owners as a cross-check. If the likely fix location is unclear, say so rather than guessing.

| Likely fix files | Component |
| --- | --- |
| `Lib/test/` | `tests` |
| `Doc/` | `docs` |
| `Lib/` | `stdlib` |
| `Modules/` | `extension-modules` |
| `Objects/`, `Python/`, `Grammar/`, `Parser/`, `Include/` | `interpreter-core` |
| `PCbuild/`, `Tools/build/`, `Tools/wasm/`, `Android/`, `iOS/`, `Mac/`, `configure`, `Makefile.pre.in`, `pyconfig.h.in` | `build` |
| `.github/`, `.azure-pipelines/` | `infra` |

When an issue spans areas, identify the likely code change that addresses the reported problem; add other applicable labels only when they describe a separate, supported aspect. A failing test does not by itself make `tests` the component if the likely correction is in the implementation. A documentation issue does not by itself make another component appropriate because the documented API is implemented elsewhere.
