# Duplicate policy

About 3% of the issues in the training data were closed as duplicates of an earlier
one. Closing a real report as a duplicate wastes the reporter's effort, so the bar is
high.

## Search

1. Query with the most specific text first: the exact error line uv printed.
2. Then "<command> <symptom>", e.g. "uv sync extras conflict lockfile".
3. Results only include issues opened before this one. Look at titles and labels;
   open the best 1-2 candidates with `get_issue`.

## Call it a duplicate only if

- the earlier issue describes the **same root cause** with the same observable behaviour
  (same command, same wrong result or error), and
- a fix for the earlier issue would also fix this one; or, for a feature request, the
  earlier issue asks for the same capability.

It is **not** a duplicate when the two issues only share a command or an area, when one
is a question and the other a bug, or when this issue reports a *different* symptom in
code the earlier fix touched (that is a regression: a new bug).

## Confidence

- 0.8-0.95: same error message, same command, same setup.
- 0.5-0.7: very likely the same cause, but described differently.
- Below 0.5: do not set `duplicate_of`; list it in `duplicate_candidates` instead.
