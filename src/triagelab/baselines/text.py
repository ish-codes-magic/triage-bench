"""How an issue snapshot becomes model input text."""

from triagelab.data.models import IssueSnapshot


def issue_text(issue: IssueSnapshot, max_chars: int | None = None) -> str:
    """Title and body, optionally truncated.

    Truncation keeps the head of the body, where reporters put the summary; long bodies
    are mostly pasted logs.
    """
    text = f"{issue.title}\n\n{issue.body}"
    return text if max_chars is None or len(text) <= max_chars else text[:max_chars]
