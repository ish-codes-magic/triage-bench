"""Local embedding encoders. The default is Snowflake arctic-embed-s on fastembed (ONNX, CPU).

Chosen by the owner on 2026-09-29 (ADR-0020): Apache-2.0, released April 2024 (before the
evaluation window), top retrieval score in its size class, and about 320 MB of RAM with
ONNX Runtime's memory arena disabled; no PyTorch needed.
"""

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from triagelab.retrieval.dense import Matrix, l2_normalise

ARCTIC_S = "snowflake/snowflake-arctic-embed-s"
# arctic-embed's documented prefix for *queries* in asymmetric (query -> passage) retrieval.
ARCTIC_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
# The model reads 512 tokens; cutting very long bodies (mostly logs) first saves tokenising.
_MAX_CHARS = 4000


class FastEmbedEncoder:
    def __init__(
        self,
        model_name: str = ARCTIC_S,
        *,
        cache_dir: Path = Path(".cache/fastembed"),
        query_prefix: str = "",
        batch_size: int = 8,
    ) -> None:
        from fastembed import TextEmbedding  # heavy import, only when dense retrieval is used

        self._name = model_name
        self._query_prefix = query_prefix
        self._batch_size = batch_size
        # The memory arena keeps peak RSS near 1.3 GB; disabled, about 320 MB (measured).
        self._model = TextEmbedding(
            model_name, cache_dir=str(cache_dir), enable_cpu_mem_arena=False
        )

    @property
    def name(self) -> str:
        return self._name

    def _embed(self, texts: Sequence[str]) -> Matrix:
        vectors = list(
            self._model.embed([t[:_MAX_CHARS] for t in texts], batch_size=self._batch_size)
        )
        return l2_normalise(np.stack(vectors).astype(np.float32))

    def encode_documents(self, texts: Sequence[str]) -> Matrix:
        return self._embed(texts)

    def encode_queries(self, texts: Sequence[str]) -> Matrix:
        return self._embed([self._query_prefix + t for t in texts])
