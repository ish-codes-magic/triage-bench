# sklearn ships without type stubs. Rather than loosen strict mode project-wide, this one
# module relaxes only the "unknown type" reports that originate in sklearn/numpy calls; its
# public surface (constructor and `triage`) is fully typed.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportAttributeAccessIssue=false
"""TF-IDF + logistic regression baseline, plus TF-IDF nearest-neighbour duplicate search.

Why TF-IDF and not embeddings (yet): the local embedding model is chosen in M3, where
dense retrieval needs it anyway; TF-IDF is also a famously strong baseline on technical
text full of identifiers and error messages. See ADR-0016.

Leakage rules this class obeys:
  - Every model is fitted on the train split only (vocabulary and IDF included).
  - Duplicate search only considers issues created strictly *before* the query issue.
"""

from collections.abc import Sequence

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier

from triagelab.baselines.text import issue_text
from triagelab.data.models import IssueSnapshot
from triagelab.eval.dataset import EvalExample
from triagelab.eval.metrics import duplicate_prf
from triagelab.triage import TriageResult

_MAX_CHARS = 20_000
_TASKS = ("labels", "component", "duplicate", "needs_info")


def _logreg() -> LogisticRegression:
    # Balanced weights: most labels, needs-info and small components are rare.
    return LogisticRegression(max_iter=2000, class_weight="balanced")


class ClassifierTriager:
    name = "classifier"

    def __init__(
        self,
        train: Sequence[EvalExample],
        history: Sequence[IssueSnapshot],
        *,
        min_label_count: int = 10,
        duplicate_threshold: float | None = None,
    ) -> None:
        self._vec = TfidfVectorizer(
            sublinear_tf=True,
            ngram_range=(1, 2),
            min_df=2,
            max_features=100_000,
            strip_accents="unicode",
        )
        x_train = self._vec.fit_transform([issue_text(e.snapshot, _MAX_CHARS) for e in train])

        # T1: one binary classifier per label with enough triaged training examples.
        triaged = [i for i, e in enumerate(train) if e.gold.human_triaged]
        counts: dict[str, int] = {}
        for i in triaged:
            for lab in train[i].gold.labels:
                counts[lab] = counts.get(lab, 0) + 1
        self._label_names = sorted(lab for lab, c in counts.items() if c >= min_label_count)
        y = np.array(
            [[lab in train[i].gold.labels for lab in self._label_names] for i in triaged], dtype=int
        )
        self._t1 = OneVsRestClassifier(_logreg()).fit(x_train[triaged], y)

        # T3: multiclass over issues whose fix mapped to a component.
        comp_idx = [i for i, e in enumerate(train) if e.gold.component is not None]
        self._t3 = _logreg().fit(x_train[comp_idx], [train[i].gold.component for i in comp_idx])

        # T4: binary needs-info.
        self._t4 = _logreg().fit(x_train, [int(e.gold.needs_info) for e in train])

        # T2: nearest neighbour over the (time-filtered) history.
        self._history = list(history)
        self._history_matrix = self._vec.transform(
            [issue_text(h, _MAX_CHARS) for h in self._history]
        )
        self._history_created = np.array([h.created_at.timestamp() for h in self._history])
        self._history_numbers = np.array([h.number for h in self._history])
        self.duplicate_threshold = (
            duplicate_threshold if duplicate_threshold is not None else self._tune_threshold(train)
        )

    def _neighbours(self, issue: IssueSnapshot, k: int = 5) -> list[tuple[int, float]]:
        query = self._vec.transform([issue_text(issue, _MAX_CHARS)])
        sims = (self._history_matrix @ query.T).toarray().ravel()
        # Only issues that existed when this one was opened (and never itself).
        allowed = (self._history_created < issue.created_at.timestamp()) & (
            self._history_numbers != issue.number
        )
        sims = np.where(allowed, sims, -1.0)
        top = np.argsort(-sims)[:k]
        return [(int(self._history_numbers[i]), float(sims[i])) for i in top if sims[i] > 0]

    def _tune_threshold(self, train: Sequence[EvalExample]) -> float:
        """Pick the similarity cut-off that maximises duplicate F1 on the *train* split."""
        best_sim: list[float] = []
        best_num: list[int | None] = []
        for e in train:
            nn = self._neighbours(e.snapshot, k=1)
            best_num.append(nn[0][0] if nn else None)
            best_sim.append(nn[0][1] if nn else 0.0)
        gold = [e.gold.duplicate_of for e in train]
        best_t, best_f1 = 1.01, -1.0
        for t in sorted(set(best_sim), reverse=True)[:500]:
            pred = [n if s >= t else None for n, s in zip(best_num, best_sim, strict=True)]
            f1 = duplicate_prf(gold, pred).f1
            if f1 > best_f1:
                best_t, best_f1 = t, f1
        return best_t

    def triage(self, issue: IssueSnapshot) -> TriageResult:
        x = self._vec.transform([issue_text(issue, _MAX_CHARS)])

        label_probs = self._t1.predict_proba(x)[0]
        labels = [lab for lab, p in zip(self._label_names, label_probs, strict=True) if p >= 0.5]

        comp_probs = self._t3.predict_proba(x)[0]
        order = np.argsort(-comp_probs)
        candidates = [str(self._t3.classes_[i]) for i in order[:3]]

        p_info = float(self._t4.predict_proba(x)[0][1])

        neighbours = self._neighbours(issue)
        top_num, top_sim = neighbours[0] if neighbours else (None, 0.0)
        is_dup = top_num is not None and top_sim >= self.duplicate_threshold

        return TriageResult(
            issue_ref=issue.issue_ref,
            labels=labels,
            label_confidence={
                lab: float(p) for lab, p in zip(self._label_names, label_probs, strict=True)
            },
            component=candidates[0] if candidates else None,
            component_confidence=float(comp_probs[order[0]]) if len(order) else None,
            component_candidates=candidates,
            duplicate_of=top_num if is_dup else None,
            duplicate_confidence=top_sim if neighbours else None,
            duplicate_candidates=[n for n, _ in neighbours],
            needs_info=p_info >= 0.5,
            needs_info_confidence=p_info,
            decided_by=dict.fromkeys(_TASKS, "classifier"),
        )
