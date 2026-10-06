from __future__ import annotations

import hashlib
from typing import Any


def _chunk_of(item):
    """Return the underlying Chunk from either a Chunk or RetrievalHit."""
    return getattr(item, "chunk", item)


def _score_of(item):
    """Return the retrieval score from a scored retrieval hit."""
    score = getattr(item, "score", None)

    if score is None:
        return None

    try:
        return round(float(score), 4)
    except (TypeError, ValueError):
        return None


def _chunk_key(chunk) -> tuple[str, str, str]:
    """Build a stable key for matching chunks to retrieval hits."""
    return (
        str(getattr(chunk, "source_file", "") or ""),
        str(getattr(chunk, "heading", "") or ""),
        str(getattr(chunk, "chunk_id", "") or ""),
    )


def build_citations(
    retrieval,
    only_files: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build citation records from the actual scored RAG retrieval hits.

    The citation pipeline preserves:

    - source document
    - chunk/document IDs
    - title and heading
    - retrieved passage
    - document version
    - updated/published/reviewed timestamp
    - retrieval relevance score

    RetrievalResult.authoritative_sources contains bare Chunk objects,
    which do not contain the RetrievalHit.score. Therefore this function
    primarily iterates over retrieval.hits so that both Chunk metadata
    and RetrievalHit.score remain available.

    Supported metadata:

    Admin-authored KB:
        document_version
        version
        updated_at
        published_at

    Original Markdown KB:
        document_id
        last_reviewed
        effective_date
    """

    if retrieval is None:
        return []

    allowed = (
        set(only_files)
        if only_files is not None
        else None
    )

    # ------------------------------------------------------------------
    # Actual scored retrieval hits.
    #
    # RetrievedChunk:
    #   chunk: Chunk
    #   score: float
    # ------------------------------------------------------------------
    hits = list(
        getattr(retrieval, "hits", None) or []
    )

    if not hits:
        return []

    # ------------------------------------------------------------------
    # Build score lookups as a defensive fallback.
    # ------------------------------------------------------------------
    score_by_key: dict[
        tuple[str, str, str],
        float,
    ] = {}

    score_by_file_heading: dict[
        tuple[str, str],
        float,
    ] = {}

    for hit in hits:
        chunk = _chunk_of(hit)
        score = _score_of(hit)

        if score is None:
            continue

        key = _chunk_key(chunk)
        score_by_key[key] = score

        file_heading = (
            str(
                getattr(
                    chunk,
                    "source_file",
                    "",
                )
                or ""
            ),
            str(
                getattr(
                    chunk,
                    "heading",
                    "",
                )
                or ""
            ),
        )

        score_by_file_heading[file_heading] = score

    # ------------------------------------------------------------------
    # Build a set of authoritative source files.
    #
    # We still respect RetrievalResult.authoritative_sources so that
    # inactive/non-official/non-customer-facing chunks cannot become
    # customer citations.
    # ------------------------------------------------------------------
    authoritative_sources = list(
        getattr(
            retrieval,
            "authoritative_sources",
            None,
        )
        or []
    )

    authoritative_keys: set[
        tuple[str, str, str]
    ] = set()

    authoritative_files: set[str] = set()

    for authoritative in authoritative_sources:
        chunk = _chunk_of(authoritative)

        source_file = str(
            getattr(
                chunk,
                "source_file",
                "",
            )
            or ""
        )

        if not source_file:
            continue

        authoritative_files.add(source_file)
        authoritative_keys.add(
            _chunk_key(chunk)
        )

    # ------------------------------------------------------------------
    # If authoritative_sources is unavailable/empty, retain compatibility
    # with older RetrievalResult implementations.
    # ------------------------------------------------------------------
    use_authoritative_filter = bool(
        authoritative_sources
    )

    out: list[dict[str, Any]] = []

    seen: set[str] = set()

    # ------------------------------------------------------------------
    # IMPORTANT:
    #
    # Iterate over the REAL RetrievalHit objects.
    #
    # This preserves:
    #
    #   hit.chunk.metadata
    #   hit.score
    #
    # instead of converting the hit to a bare Chunk first.
    # ------------------------------------------------------------------
    for hit in hits:
        chunk = _chunk_of(hit)

        source_file = str(
            getattr(
                chunk,
                "source_file",
                "",
            )
            or ""
        )

        if not source_file:
            continue

        # Respect an explicit file filter.
        if (
            allowed is not None
            and source_file not in allowed
        ):
            continue

        # --------------------------------------------------------------
        # Customer-facing citation safety filter.
        # --------------------------------------------------------------
        if use_authoritative_filter:
            chunk_key = _chunk_key(chunk)

            if (
                chunk_key not in authoritative_keys
                and source_file not in authoritative_files
            ):
                continue
        else:
            # Defensive fallback for older retrieval implementations.
            if not (
                getattr(
                    chunk,
                    "is_active_official",
                    False,
                )
                and getattr(
                    chunk,
                    "is_customer_facing",
                    False,
                )
            ):
                continue

        heading = str(
            getattr(
                chunk,
                "heading",
                "",
            )
            or ""
        )

        text = str(
            getattr(
                chunk,
                "text",
                "",
            )
            or ""
        )

        metadata = dict(
            getattr(
                chunk,
                "metadata",
                None,
            )
            or {}
        )

        # --------------------------------------------------------------
        # Stable citation ID.
        # --------------------------------------------------------------
        cid = (
            "cit_"
            + hashlib.sha256(
                (
                    f"{source_file}|"
                    f"{heading}|"
                    f"{text}"
                ).encode("utf-8")
            ).hexdigest()[:12]
        )

        if cid in seen:
            continue

        seen.add(cid)

        # --------------------------------------------------------------
        # Document version.
        #
        # Admin KB:
        #   document_version
        #   version
        #
        # Original Markdown:
        #   document_id
        #
        # document_id is used as a stable source revision identifier
        # when no explicit version exists.
        # --------------------------------------------------------------
        document_version = (
            metadata.get(
                "document_version"
            )
            or metadata.get(
                "version"
            )
            or metadata.get(
                "document_id"
            )
            or getattr(
                chunk,
                "document_id",
                None,
            )
        )

        if document_version is not None:
            document_version = str(
                document_version
            )

        # --------------------------------------------------------------
        # Updated timestamp.
        #
        # Admin KB:
        #   updated_at
        #   published_at
        #
        # Original Markdown:
        #   last_reviewed
        #   effective_date
        # --------------------------------------------------------------
        updated_at = (
            metadata.get(
                "updated_at"
            )
            or metadata.get(
                "published_at"
            )
            or metadata.get(
                "last_reviewed"
            )
            or metadata.get(
                "effective_date"
            )
        )

        if updated_at is not None:
            updated_at = str(
                updated_at
            )

        # --------------------------------------------------------------
        # Retrieval relevance.
        #
        # PRIMARY:
        #   actual RetrievalHit.score
        #
        # FALLBACK:
        #   score lookup by chunk identity
        #
        # FALLBACK:
        #   source_file + heading
        # --------------------------------------------------------------
        relevance_score = _score_of(hit)

        if relevance_score is None:
            relevance_score = score_by_key.get(
                _chunk_key(chunk)
            )

        if relevance_score is None:
            relevance_score = (
                score_by_file_heading.get(
                    (
                        source_file,
                        heading,
                    )
                )
            )

        # --------------------------------------------------------------
        # Passage.
        # --------------------------------------------------------------
        passage = text[:1200]

        # --------------------------------------------------------------
        # Final citation record.
        # --------------------------------------------------------------
        out.append(
            {
                "id": cid,

                "chunk_id": getattr(
                    chunk,
                    "chunk_id",
                    None,
                ),

                "document_id": (
                    getattr(
                        chunk,
                        "document_id",
                        None,
                    )
                    or metadata.get(
                        "document_id"
                    )
                ),

                "document": source_file,

                "title": (
                    metadata.get(
                        "title"
                    )
                    or getattr(
                        chunk,
                        "title",
                        None,
                    )
                    or source_file
                ),

                "heading": heading,

                "passage": passage,

                "document_version": (
                    document_version
                    if document_version
                    else None
                ),

                "source_type": (
                    "knowledge_base"
                ),

                "updated_at": (
                    updated_at
                    if updated_at
                    else None
                ),

                "relevance_score": (
                    relevance_score
                    if relevance_score is not None
                    else None
                ),
            }
        )

    return out