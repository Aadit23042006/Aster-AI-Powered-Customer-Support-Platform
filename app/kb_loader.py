"""Loads the Markdown knowledge base and splits it into retrievable chunks.

Design notes
------------
Each file's YAML front matter (status, policy_authority, audience, document_id,
supersedes/superseded_by, customer_answering) is preserved on *every chunk*
produced from that file, not just at the document level. That metadata is
what `retriever.py` uses to decide whether a chunk is allowed to be cited as
authority, and it is exactly what the assignment asks for ("preserve useful
metadata from the document front matter").

Chunking is by H2 (`##`) section, which matches how these policy docs are
actually authored -- each `##` is a self-contained sub-topic ("Standard
return window", "Item condition", ...). Chunking at this granularity keeps
retrieved passages focused instead of pulling an entire multi-topic document
into context for every question.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Chunk:
    chunk_id: str
    source_file: str          # e.g. "01-returns-policy-current.md"
    document_id: str
    title: str
    heading: str               # the H2 heading this chunk falls under (or "Overview")
    text: str                  # heading + body, what gets embedded/shown to the model
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active_official(self) -> bool:
        """Whether this chunk may be used/cited as authoritative policy."""
        return (
            self.metadata.get("status") == "active"
            and self.metadata.get("policy_authority") == "official"
        )

    @property
    def is_customer_facing(self) -> bool:
        # customer_answering defaults to True unless explicitly set False
        # (only 14-internal-content-migration-notes.md sets it false), and
        # audience must not be "internal".
        if self.metadata.get("customer_answering", True) is False:
            return False
        return self.metadata.get("audience") != "internal"

    @property
    def category(self) -> str:
        """Coarse category derived from the document_id prefix (e.g.
        "RET-2026-01" -> "RET"). Used for Hybrid RAG metadata filtering
        (Feature 12) and for the Knowledge Base admin document list
        (Feature 13) -- a lightweight derived field rather than a new
        front-matter key, since every document already has a document_id."""
        return self.document_id.split("-")[0].upper() if self.document_id else "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_file": self.source_file,
            "document_id": self.document_id,
            "title": self.title,
            "heading": self.heading,
            "text": self.text,
            "metadata": self.metadata,
        }


# Documents that describe how the *agent itself* should behave (escalation
# rules, handoff triggers) rather than customer-answerable content. These are
# loaded directly into the system prompt as trusted operational policy -- see
# app/agent.py -- instead of going into the semantic retrieval index.
#
# Why: early testing showed 13-support-escalation.md ("The agent should
# recommend human assistance when...") shares enough vocabulary with the
# real policy docs (return, policy, order) that it was being retrieved as a
# top-3 hit for plain return-window questions, displacing the actual policy
# chunk. It isn't customer content at all, so it should never have been in
# the customer-retrieval index in the first place. See bug diary entry #1
# in the README.
AGENT_POLICY_FILES: set[str] = {"13-support-escalation.md"}

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_H2_SPLIT_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _parse_front_matter(raw: str) -> tuple[dict[str, Any], str]:
    m = _FRONT_MATTER_RE.match(raw)
    if not m:
        return {}, raw
    fm_text, body = m.group(1), m.group(2)
    metadata = yaml.safe_load(fm_text) or {}
    # PyYAML auto-parses unquoted dates (effective_date, last_reviewed, ...)
    # into datetime.date objects, which json.dumps can't serialize -- and
    # the index cache (retriever.VectorIndex.save) is plain JSON. Stringify
    # them here, once, rather than special-casing every downstream consumer.
    for key, value in list(metadata.items()):
        if isinstance(value, (datetime.date, datetime.datetime)):
            metadata[key] = value.isoformat()
    return metadata, body


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split a document body into (heading, section_text) pairs on H2s.
    Any text before the first H2 is kept as an "Overview" section (this is
    where doc 02's blockquote intro and doc 14's intro paragraph live)."""
    h1_match = _H1_RE.search(body)
    title_line_end = h1_match.end() if h1_match else 0
    remainder = body[title_line_end:].strip("\n")

    pieces = _H2_SPLIT_RE.split(remainder)
    # pieces = [pre_text, heading1, section1, heading2, section2, ...]
    sections: list[tuple[str, str]] = []
    pre_text = pieces[0].strip()
    if pre_text:
        sections.append(("Overview", pre_text))
    for i in range(1, len(pieces), 2):
        heading = pieces[i].strip()
        text = pieces[i + 1].strip() if i + 1 < len(pieces) else ""
        if text:
            sections.append((heading, text))
    if not sections:
        # No H2 headings at all -- treat the whole body as one chunk.
        sections.append(("Overview", remainder.strip()))
    return sections


def chunks_from_body(
    *, source_file: str, document_id: str, title: str, body: str, metadata: dict[str, Any]
) -> list[Chunk]:
    """Splits one document's already-front-matter-stripped body into
    `Chunk`s by H2 section, tagging every chunk with `metadata`. Shared by
    `load_knowledge_base` (the original file-based Phase 1 corpus) and the
    Knowledge Base admin re-indexing pipeline (Phase 2 Feature 14, see
    `app/services/kb_service.py::chunks_for_document`), so both sources
    produce identically-shaped `Chunk`s and the retriever/agent stay
    completely unaware of which one a given chunk came from."""
    chunks: list[Chunk] = []
    for idx, (heading, text) in enumerate(_split_sections(body)):
        chunk_text = f"# {title}\n## {heading}\n\n{text}" if heading != "Overview" else f"# {title}\n\n{text}"
        chunks.append(
            Chunk(
                chunk_id=f"{source_file}::{idx}::{heading}"[:120],
                source_file=source_file,
                document_id=document_id,
                title=title,
                heading=heading,
                text=chunk_text,
                metadata=metadata,
            )
        )
    return chunks


def load_knowledge_base(kb_dir: Path, exclude_files: set[str] = AGENT_POLICY_FILES) -> list[Chunk]:
    """Load the customer-facing retrieval index. `exclude_files` is skipped
    entirely (see AGENT_POLICY_FILES docstring above) -- pass an empty set to
    include everything, e.g. for inspecting the raw corpus."""
    chunks: list[Chunk] = []
    for path in sorted(kb_dir.glob("*.md")):
        if path.name in exclude_files:
            continue
        raw = path.read_text(encoding="utf-8")
        metadata, body = _parse_front_matter(raw)
        h1_match = _H1_RE.search(body)
        title = h1_match.group(1).strip() if h1_match else metadata.get("title", path.stem)
        document_id = metadata.get("document_id", path.stem)
        chunks.extend(
            chunks_from_body(source_file=path.name, document_id=document_id, title=title, body=body, metadata=metadata)
        )
    return chunks


def load_agent_policy_text(kb_dir: Path, files: set[str] = AGENT_POLICY_FILES) -> str:
    """Raw (front-matter-stripped) text of the operational/agent-config docs,
    for direct inclusion in the system prompt. Trusted: these ship in the
    repo, they are never retrieved from a vector search over content that
    could later be edited/poisoned independently of a code review."""
    parts = []
    for path in sorted(kb_dir.glob("*.md")):
        if path.name not in files:
            continue
        _, body = _parse_front_matter(path.read_text(encoding="utf-8"))
        parts.append(body.strip())
    return "\n\n".join(parts)


if __name__ == "__main__":  # quick manual smoke check
    import sys

    kb_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "knowledge-base"
    all_chunks = load_knowledge_base(kb_path)
    print(f"Loaded {len(all_chunks)} chunks from {kb_path}")
    for c in all_chunks[:5]:
        print("-", c.chunk_id, "| active_official=", c.is_active_official)
