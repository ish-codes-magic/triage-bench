# Needs-info checklist

uv's `needs-mre` label: "Needs more information for reproduction". Set `needs_info` only
when a maintainer could not reproduce the problem from what the reporter gave. Most
reports (about 95% in the training data) do not need it.

## A bug report usually needs a reproduction when

- it shows an error but not the command that produced it;
- the failure depends on a project the maintainer cannot see: no `pyproject.toml`, no
  lockfile excerpt, no list of requirements, and the text alone doesn't identify them;
- it says something "doesn't work" or "is slow" without the output (`-v` output is what
  maintainers ask for);
- it depends on a private index, a proxy or an unusual environment and doesn't show
  enough to tell whether uv is at fault.

## Usually not

- questions, feature requests and documentation issues: they need an answer or a
  discussion, not a reproduction;
- short reports that are nevertheless precise (one command and its error are enough);
- a missing uv version or platform alone, when the behaviour clearly doesn't depend on it.

List what is missing in `missing_info` using short phrases, e.g. `"command"`,
`"pyproject.toml"`, `"verbose output"`, `"uv version"`, `"platform"`.
