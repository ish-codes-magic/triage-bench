from datetime import UTC, datetime, timedelta

from triagelab.baselines.classifier import ClassifierTriager
from triagelab.baselines.majority import MajorityTriager
from triagelab.baselines.text import issue_text
from triagelab.data.models import IssueSnapshot
from triagelab.eval.dataset import EvalExample, Gold

T0 = datetime(2025, 6, 1, tzinfo=UTC)

# Distinctive vocab per class so a tiny TF-IDF model can learn it.
TOPICS = {
    "stdlib": ("asyncio event loop cancels task pathlib glob", "type-bug"),
    "interpreter-core": ("segfault refcount object dealloc bytecode", "type-crash"),
    "docs": ("typo in documentation howto sphinx page", "type-feature"),
}


def snap(n: int, text: str, at: datetime) -> IssueSnapshot:
    return IssueSnapshot(
        issue_ref=f"python/cpython#{n}",
        repo="python/cpython",
        number=n,
        title=text.split()[0],
        body=text,
        author_association="NONE",
        created_at=at,
    )


def train_set() -> list[EvalExample]:
    out: list[EvalExample] = []
    n = 1
    for i in range(12):
        for comp, (text, type_label) in TOPICS.items():
            info = comp == "docs" and i % 2 == 0
            out.append(
                EvalExample(
                    snapshot=snap(
                        n,
                        f"{text} variant {i}" + (" please provide version" if info else ""),
                        T0 + timedelta(hours=n),
                    ),
                    gold=Gold(
                        labels=frozenset({type_label, comp}),
                        label_groups={type_label: "type", comp: "area"},
                        human_triaged=True,
                        duplicate_of=None,
                        component=comp,
                        needs_info=info,
                    ),
                    split="train",
                    weight=1.0,
                )
            )
            n += 1
    return out


def test_issue_text_truncates_keeping_the_head() -> None:
    s = snap(1, "x" * 50, T0)
    full = issue_text(s)
    assert full == s.title + "\n\n" + s.body
    assert issue_text(s, max_chars=10) == full[:10]


def test_majority_predicts_the_mode() -> None:
    train = train_set()
    extra = train[0].model_copy(
        update={"gold": train[0].gold.model_copy(update={"component": "stdlib"})}
    )
    result = MajorityTriager([*train, extra]).triage(snap(999, "anything", T0 + timedelta(days=90)))
    assert result.component == "stdlib"
    assert result.component_candidates[0] == "stdlib"
    assert not result.needs_info
    assert result.duplicate_of is None


def test_classifier_learns_components_and_labels() -> None:
    train = train_set()
    clf = ClassifierTriager(
        train, [e.snapshot for e in train], min_label_count=3, duplicate_threshold=0.99
    )
    query = snap(999, "segfault in object dealloc with refcount bytecode", T0 + timedelta(days=90))
    result = clf.triage(query)
    assert result.component == "interpreter-core"
    assert "type-crash" in result.labels
    assert len(result.component_candidates) == 3


def test_duplicate_search_never_looks_into_the_future() -> None:
    train = train_set()
    query_time = T0 + timedelta(days=30)
    # Mixes in-vocabulary words (the vectoriser is fitted on train only), so the three
    # issues below are near-identical to each other and only loosely similar to train.
    text = "segfault asyncio typo refcount pathlib sphinx"
    earlier = snap(500, text, query_time - timedelta(days=1))
    later = snap(501, text, query_time + timedelta(days=1))
    clf = ClassifierTriager(
        train, [*(e.snapshot for e in train), earlier, later], duplicate_threshold=0.9
    )
    result = clf.triage(snap(600, text, query_time))
    assert result.duplicate_of == 500
    assert 501 not in result.duplicate_candidates  # identical text, but it didn't exist yet
