"""Build a decision triager from config: the LLM backend, or a classifier trained on train."""

from collections.abc import Callable, Sequence
from pathlib import Path

from triagelab.config import Config, DecisionsConfig
from triagelab.data.profile import RepoProfile
from triagelab.decisions.base import DecisionBackend, DecisionError
from triagelab.decisions.classifier import CachedEncoder, ClassifierBackend, Head, fit_head
from triagelab.decisions.llm import LLMDecisionBackend
from triagelab.decisions.questions import answer_for, questions
from triagelab.decisions.triager import DecisionTriager
from triagelab.eval.dataset import EvalExample
from triagelab.llm_client import LLMClient
from triagelab.prompting import issue_block
from triagelab.retrieval.dense import Encoder


def embedding_cache(data_dir: Path, profile: RepoProfile, encoder: Encoder) -> CachedEncoder:
    name = encoder.name.replace("/", "__")
    return CachedEncoder(encoder, data_dir / "models" / profile.slug / f"decision-emb-{name}.npz")


def train_heads(
    encoder: Encoder,
    profile: RepoProfile,
    train: Sequence[EvalExample],
    question_ids: Sequence[str],
    *,
    max_body_chars: int,
    c: float,
) -> dict[str, Head]:
    """One head per question, on the training issues whose silver labels answer it.

    The classifier sees the same issue text the LLM backends get as `state`.
    """
    heads: dict[str, Head] = {}
    for qid, q in questions(profile).items():
        if qid not in question_ids:
            continue
        pairs = [(e, a) for e in train if (a := answer_for(qid, e.gold, profile)) is not None]
        if not pairs:
            raise DecisionError(f"no training issue answers the {qid!r} question")
        states = [issue_block(e.snapshot, max_body_chars) for e, _ in pairs]
        heads[q.text] = fit_head(encoder.encode_documents(states), [a for _, a in pairs], c=c)
    return heads


def build_decision_triager(
    cfg: Config,
    decisions: DecisionsConfig,
    profile: RepoProfile,
    train: Sequence[EvalExample],
    client: Callable[[], LLMClient],
) -> DecisionTriager:
    assert cfg.system is not None
    max_chars = cfg.system.max_body_chars
    backend: DecisionBackend
    if decisions.backend == "llm":
        backend = LLMDecisionBackend(
            client(), cfg.llm, decisions.confidence, top_logprobs=decisions.top_logprobs
        )
    else:
        from triagelab.retrieval.encoders import FastEmbedEncoder  # heavy: only when needed

        encoder = embedding_cache(cfg.dataset.data_dir, profile, FastEmbedEncoder())
        heads = train_heads(
            encoder,
            profile,
            train,
            decisions.questions,
            max_body_chars=max_chars,
            c=decisions.classifier_c,
        )
        backend = ClassifierBackend(encoder, heads)
    return DecisionTriager(backend, profile, decisions.questions, max_body_chars=max_chars)
