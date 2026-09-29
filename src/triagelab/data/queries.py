"""GraphQL documents used by the collector.

Every field here was checked against GitHub's live schema on 2026-09-29 (see the M1
learning note). Each query also asks for `rateLimit`, which the client uses to pace
itself within the 5,000 points/hour budget.
"""

RATE_LIMIT = "rateLimit { cost remaining resetAt }"

SEARCH_ISSUE_NUMBERS = f"""
query($q: String!, $cursor: String) {{
  {RATE_LIMIT}
  search(query: $q, type: ISSUE, first: 100, after: $cursor) {{
    issueCount
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ ... on Issue {{ number }} }}
  }}
}}
"""

# Timeline events we need: labels (T1/T4 and provenance), state changes and duplicate
# marks (T2), title renames (to reconstruct the original title), and cross-references
# from PRs (T3, because CPython links PRs by title rather than "fixes #N").
_TIMELINE_TYPES = (
    "LABELED_EVENT, UNLABELED_EVENT, CLOSED_EVENT, REOPENED_EVENT, "
    "MARKED_AS_DUPLICATE_EVENT, UNMARKED_AS_DUPLICATE_EVENT, "
    "RENAMED_TITLE_EVENT, CROSS_REFERENCED_EVENT"
)

_PR_SUMMARY = "number title merged mergedAt baseRefName"

ISSUE_FIELDS = f"""
fragment IssueFields on Issue {{
  number url title body createdAt closedAt state stateReason lastEditedAt authorAssociation
  author {{ __typename login }}
  labels(first: 30) {{ nodes {{ name }} }}
  duplicateOf {{ number createdAt }}
  originalBody: userContentEdits(last: 1) {{
    nodes {{ editedAt diff editor {{ __typename login }} }}
  }}
  comments(first: 40) {{
    totalCount
    nodes {{ createdAt body authorAssociation author {{ __typename login }} }}
  }}
  closedByPullRequestsReferences(first: 5, includeClosedPrs: true) {{
    nodes {{ {_PR_SUMMARY} }}
  }}
  timelineItems(first: 100, itemTypes: [{_TIMELINE_TYPES}]) {{
    totalCount
    nodes {{
      __typename
      ... on LabeledEvent {{ createdAt label {{ name }} actor {{ __typename login }} }}
      ... on UnlabeledEvent {{ createdAt label {{ name }} actor {{ __typename login }} }}
      ... on ClosedEvent {{ createdAt stateReason duplicateOf {{ ... on Issue {{ number }} }} }}
      ... on ReopenedEvent {{ createdAt }}
      ... on MarkedAsDuplicateEvent {{
        createdAt actor {{ __typename login }}
        canonical {{ __typename ... on Issue {{ number createdAt }} }}
      }}
      ... on UnmarkedAsDuplicateEvent {{
        createdAt canonical {{ __typename ... on Issue {{ number createdAt }} }}
      }}
      ... on RenamedTitleEvent {{ createdAt previousTitle currentTitle }}
      ... on CrossReferencedEvent {{
        createdAt source {{ __typename ... on PullRequest {{ {_PR_SUMMARY} }} }}
      }}
    }}
  }}
}}
"""


def issues_batch_query(numbers: list[int]) -> str:
    """One query fetching several issues at once via aliases (`i123: issue(number: 123)`)."""
    aliases = "\n    ".join(f"i{n}: issue(number: {n}) {{ ...IssueFields }}" for n in numbers)
    return f"""
query($owner: String!, $name: String!) {{
  {RATE_LIMIT}
  repository(owner: $owner, name: $name) {{
    {aliases}
  }}
}}
{ISSUE_FIELDS}
"""


def pr_files_batch_query(numbers: list[int]) -> str:
    aliases = "\n    ".join(
        f"p{n}: pullRequest(number: {n}) {{ number files(first: 100) "
        "{ totalCount nodes { path } } }"
        for n in numbers
    )
    return f"""
query($owner: String!, $name: String!) {{
  {RATE_LIMIT}
  repository(owner: $owner, name: $name) {{
    {aliases}
  }}
}}
"""
