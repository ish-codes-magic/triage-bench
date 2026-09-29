---
name: generic-triage
description: General-purpose GitHub issue triage for any repository - classify the issue type, pick area labels from the allowed list, find the component a fix would change, check for duplicates of earlier issues, and decide whether the reporter must provide more information. Use when triaging an issue and no repository-specific skill applies.
license: MIT
---

# Triaging a GitHub issue

You see the issue exactly as it was first opened. Decide with as few tool calls as you
can; most issues need 2-6.

1. **Classify the report.** Is it a bug (wrong behaviour or an error), a crash (the
   program itself dies), a feature request, a documentation problem, or a build/CI
   problem? Pick exactly one type label from the allowed list.
2. **Check for duplicates.** Search earlier issues with the most specific text you have
   (the error message first, then the component and symptom). Only call it a duplicate
   if an earlier issue has the same root cause and the same observable behaviour; when in
   doubt, list candidates instead.
3. **Locate the code.** Search the code for the function, class or file the report names.
   The component is the directory a fix would change, not the topic of the report.
4. **Pick labels.** Area labels follow the component. Add narrower topic or platform
   labels only when the issue is clearly about them. Use only labels from the allowed
   list, copied exactly.
5. **Missing information.** Flag it only when a maintainer could not start without an
   answer: no reproduction, no error output, or an unknown version for a version-specific
   problem. Feature requests rarely need it.
6. **Submit** once with calibrated confidences (0.9 means right 9 times in 10) and a
   1-3 sentence comment a maintainer could post: concrete, polite, no promises.
