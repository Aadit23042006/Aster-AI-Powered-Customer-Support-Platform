"""Keyword/exact-match retrieval -- the second arm of Hybrid RAG (Phase 2,
Feature 12), alongside the existing semantic vector search in
`app/retriever.py`.

Why a hand-rolled BM25 instead of Postgres full-text search: the retrieval
corpus at this stage is still the ~50 chunks parsed from the 14 Markdown
files in `knowledge-base/` (see `app/kb_loader.py`), the same corpus the
vector index is built from -- it does not live in Postgres yet. Feature 13
(Knowledge Base admin) and Feature 14 (automatic re-indexing) move document
*storage/authoring* into Postgres; once that lands, the re-indexing job can
rebuild this same `BM25Index` (or a `to_tsvector`/`plainto_tsquery` query
against a real `knowledge_documents` table) from the DB-backed corpus
without changing anything downstream -- `Retriever` only ever calls
`.score_all(query)`, exactly the same encapsulation `app/agent.py` uses to
stay agnostic of the underlying order-lookup implementation
(`Agent.set_order_tool`). For this corpus size, a dependency-free BM25 index
is effectively instant and fully deterministic for tests, matching this
repo's existing "no framework abstraction at this scale" design choice
(see README's "Design choices" table).

BM25 (Robertson/Sparck-Jones), standard Okapi parameters.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from app.kb_loader import Chunk

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Standard Okapi BM25 tuning constants.
_K1 = 1.5
_B = 0.75

# A small, standard English stopword list. Function words like "do"/"you"/
# "the" appear in nearly every chunk regardless of topic, so leaving them
# in inflates BM25 scores almost uniformly across the whole corpus for any
# naturally-phrased question ("Do you ship internationally?") -- which
# would make the keyword arm noise rather than signal, and could trigger
# false conflict-watchlist hits purely from shared function words. This is
# standard practice for BM25/TF-IDF style keyword search, not a
# domain-specific hack.
_STOPWORDS: frozenset[str] = frozenset(
    """
    a an the and or but if while is are was were be been being do does did
    to of in on for with at by from as it its this that these those i you
    he she we they what which who whom my your his her our their me him
    them us am not no yes can could will would should shall may might must
    have has had having so than then there here when where why how all
    any both each few more most other some such only own same too very
    just about into over under up down out off again further once
    """.split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


class BM25Index:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self._doc_tokens: list[list[str]] = [tokenize(c.text) for c in chunks]
        self._doc_len: list[int] = [len(t) for t in self._doc_tokens]
        self._avg_len: float = (sum(self._doc_len) / len(self._doc_len)) if self._doc_tokens else 0.0
        self._doc_term_counts: list[Counter[str]] = [Counter(t) for t in self._doc_tokens]

        self._n = len(chunks)
        self._df: Counter[str] = Counter()
        for tokens in self._doc_tokens:
            for term in set(tokens):
                self._df[term] += 1

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        # +1 smoothing keeps idf non-negative for very common terms and
        # finite (rather than -inf) for terms present in every document.
        return math.log(1 + (self._n - df + 0.5) / (df + 0.5))

    def score_all(self, query: str) -> list[float]:
        """Returns one BM25 score per chunk, in `self.chunks` order, for
        `query`. Chunks with no query-term overlap score exactly 0.0, so
        callers can tell "no keyword match" apart from "weak match"."""
        q_terms = tokenize(query)
        scores = [0.0] * self._n
        if not q_terms or self._n == 0:
            return scores

        term_idf = {term: self._idf(term) for term in set(q_terms)}
        for i in range(self._n):
            dl = self._doc_len[i]
            if dl == 0:
                continue
            counts = self._doc_term_counts[i]
            total = 0.0
            for term in q_terms:
                tf = counts.get(term, 0)
                if tf == 0:
                    continue
                idf = term_idf[term]
                denom = tf + _K1 * (1 - _B + _B * dl / (self._avg_len or 1))
                total += idf * (tf * (_K1 + 1)) / denom
            scores[i] = total
        return scores
