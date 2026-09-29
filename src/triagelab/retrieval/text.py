"""Tokenisation for lexical retrieval.

Issue text is full of identifiers (`asyncio.TaskGroup`, `PyObject_GetAttr`), error names
and paths, so tokens are identifier-shaped words, lower-cased. Dotted names split into
parts, so "asyncio.run" matches both "asyncio" and "run".
"""

import re

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")

# Deliberately small: technical words like "not", "error" and "file" carry signal here.
_STOPWORD_TEXT = """
    a an and are as at be but by for from has have i if in into is it its of on or so that
    the their then there these this to was were will with you your we our can could should
    would do does did been being when which what who how
"""
STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def tokenize(text: str, max_tokens: int | None = None) -> list[str]:
    tokens = [t.lower() for t in _TOKEN.findall(text)]
    tokens = [t for t in tokens if len(t) > 1 and t not in STOPWORDS]
    return tokens if max_tokens is None else tokens[:max_tokens]
