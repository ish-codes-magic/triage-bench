# uv component map

The component is the group of crates a fix would change. The first matching row wins, so
`crates/uv/tests/` is `tests` even though it is under `crates/uv/`. This table mirrors
`configs/repos/astral-sh__uv.yaml` (a test keeps them in sync).

| component | directories |
|---|---|
| `tests` | `crates/uv/tests/`, `crates/uv-test/`, `test/` |
| `docs` | `docs/`, `README.md`, `mkdocs.yml` |
| `resolver` | `crates/uv-resolver/`, `crates/uv-pep440/`, `crates/uv-pep508/`, `crates/uv-platform-tags/`, `crates/uv-requirements/`, `crates/uv-requirements-txt/`, `crates/uv-pypi-types/`, `crates/uv-normalize/`, `crates/uv-torch/` |
| `installer` | `crates/uv-installer/`, `crates/uv-install-wheel/`, `crates/uv-extract/`, `crates/uv-distribution/`, `crates/uv-distribution-types/`, `crates/uv-distribution-filename/`, `crates/uv-virtualenv/`, `crates/uv-trampoline/`, `crates/uv-trampoline-builder/` |
| `python` | `crates/uv-python/`, `crates/uv-bin-install/`, `crates/uv-platform/` |
| `network` | `crates/uv-client/`, `crates/uv-auth/`, `crates/uv-keyring/`, `crates/uv-netrc/`, `crates/uv-publish/`, `crates/uv-git/`, `crates/uv-git-types/`, `crates/uv-redacted/` |
| `cache` | `crates/uv-cache/`, `crates/uv-cache-info/`, `crates/uv-cache-key/` |
| `build` | `crates/uv-build-backend/`, `crates/uv-build-frontend/`, `crates/uv-build/`, `crates/uv-dispatch/` |
| `projects` | `crates/uv-workspace/`, `crates/uv-scripts/`, `crates/uv-tool/`, `crates/uv-state/` |
| `cli` | `crates/uv/`, `crates/uv-cli/`, `crates/uv-settings/`, `crates/uv-configuration/`, `crates/uv-options-metadata/`, `crates/uv-console/`, `crates/uv-warnings/`, `crates/uv-logging/`, `crates/uv-shell/` |
| `infra` | `.github/`, `scripts/`, `Dockerfile`, `dist-workspace.toml` |

In the training data the most common component is `cli` (35% of issues with a known
fix), then `resolver` (16%), `installer` (12%) and `python` (8%).

## Finding the crate group

- `search_code` with the exact error message or the option name. Error strings and the
  code that raises them usually live in the crate that owns the behaviour.
- `cli` is the `uv` binary crate: command implementations (`crates/uv/src/commands/`),
  argument parsing, settings and output. A wrong flag, a missing option, a confusing
  message printed by a command, or behaviour of `uv run` / `uv sync` / `uv pip` that is
  decided in the command code belongs here. It is the largest group.
- `resolver`: the dependency solution is wrong or cannot be found, markers and version
  specifiers are parsed or evaluated wrongly, platform tags, `requirements.txt` parsing.
- `installer`: wheels are unpacked, linked or installed wrongly; virtual environment
  creation; entry-point launchers ("trampolines") on Windows.
- `python`: finding, downloading or installing Python interpreters (`uv python ...`).
- `network`: registries and indexes, authentication, keyring, proxies, Git sources,
  publishing.
- `build`: building source distributions and wheels, uv's own build backend.
- `projects`: workspace discovery, inline script metadata, `uv tool` state.
- `get_codeowners` on a path lists its owners, useful for `suggested_owners`.

If a fix would touch several groups, choose the one holding the actual behaviour change;
integration tests under `crates/uv/tests/` and docs usually change alongside it and are
not the component.
