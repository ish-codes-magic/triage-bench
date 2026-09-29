# Needs-info checklist

CPython's `pending` label: "The issue will be closed if no feedback is provided." Set
`needs_info` only when a maintainer could not start working without an answer from the
reporter. Most reports (about 88% in the training data) do not need it.

## A bug or crash usually needs information when

- there is no way to reproduce it: no code, no command, no steps, and the text alone
  doesn't identify the failing call;
- the Python version is unknown *and* the behaviour could be version-specific
  (a regression, something fixed recently);
- it describes an error without the traceback or message;
- it depends on a third-party package or unusual environment and doesn't show that
  CPython itself is at fault.

## Usually not

- feature requests and docs issues: they need discussion, not missing facts;
- short reports that are nevertheless precise (a one-line reproducer is enough);
- reports from core developers or triagers describing a known problem.

List what is missing in `missing_info` using short phrases, e.g. `"python version"`,
`"reproducer"`, `"traceback"`, `"operating system"`.
