"""
Knowledge base loader and BM25-lite retrieval.

Scans the knowledge/ directory for Markdown files, builds an in-memory
inverted index, and retrieves relevant excerpts for a given query.

No external vector store — pure Python BM25-style scoring.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from agent.prompt import KnowledgeExcerpt

import config


@dataclass
class KnowledgeDoc:
    """A single knowledge base document."""

    doc_id: str
    text: str
    category: str  # philosophy, interviews, biography, projects
    tags: list[str] = field(default_factory=list)
    source: str = ""  # original filename


class KnowledgeIndex:
    """In-memory inverted index over knowledge files."""

    CATEGORY_BOOST: dict[str, float] = {
        "philosophy": 1.3,
        "projects": 1.2,
        "interviews": 1.1,
        "biography": 1.0,
    }

    def __init__(self):
        self.documents: dict[str, KnowledgeDoc] = {}
        self.term_index: dict[str, set[str]] = {}  # term -> set of doc_ids
        self.doc_lengths: dict[str, int] = {}      # doc_id -> word_count

    # ── Indexing ────────────────────────────────────────────────────

    def add_document(self, doc_id: str, text: str, category: str,
                     tags: list[str] | None = None, source: str = "") -> None:
        """Add a document to the index."""
        tags = tags or []
        self.documents[doc_id] = KnowledgeDoc(doc_id, text, category, tags, source)

        word_count = len(self._tokenize(text))
        self.doc_lengths[doc_id] = word_count

        # Index terms (including tags for better retrieval)
        indexable_text = text + " " + " ".join(tags)
        terms = self._tokenize(indexable_text)
        for term in terms:
            if term not in self.term_index:
                self.term_index[term] = set()
            self.term_index[term].add(doc_id)

    def remove_document(self, doc_id: str) -> None:
        """Remove a document from the index."""
        if doc_id not in self.documents:
            return
        del self.documents[doc_id]
        if doc_id in self.doc_lengths:
            del self.doc_lengths[doc_id]
        # Clean term index
        for term in list(self.term_index.keys()):
            self.term_index[term].discard(doc_id)
            if not self.term_index[term]:
                del self.term_index[term]

    # ── Retrieval ───────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        max_tokens: int = 2000,
    ) -> list[KnowledgeExcerpt]:
        """
        Retrieve the most relevant knowledge excerpts for a query.

        Uses BM25-style scoring with category boosting.
        """
        query_terms = self._tokenize(query)
        if not query_terms:
            return []

        # Score each document
        scores: dict[str, float] = {}
        n_docs = max(len(self.documents), 1)
        avg_len = (
            sum(self.doc_lengths.values()) / n_docs
            if self.doc_lengths else 1
        )

        k1, b = 1.2, 0.75

        for term in query_terms:
            if term not in self.term_index:
                continue
            docs_with_term = self.term_index[term]
            idf = math.log(n_docs / max(len(docs_with_term), 1))

            for doc_id in docs_with_term:
                tf = self._count_term(self.documents[doc_id].text, term)
                doc_len = self.doc_lengths.get(doc_id, 1)
                tf_norm = tf / (tf + k1 * (1 - b + b * doc_len / avg_len))
                scores[doc_id] = scores.get(doc_id, 0) + idf * tf_norm

        # Apply category boost
        # Detect which categories are relevant from the query
        for doc_id in list(scores.keys()):
            category = self.documents[doc_id].category
            boost = self.CATEGORY_BOOST.get(category, 1.0)

            # Extra boost if query hints match category keywords
            if category == "philosophy" and self._matches(query, [
                "哲学", "理念", "认为", "思考", "建筑", "空间", "光", "自然",
            ]):
                boost *= 1.2
            elif category == "projects" and self._matches(query, [
                "作品", "建筑", "教堂", "博物馆", "住宅", "设计",
            ]):
                boost *= 1.2
            elif category == "biography" and self._matches(query, [
                "出生", "经历", "学习", "拳击", "旅行", "年轻时",
            ]):
                boost *= 1.2
            elif category == "interviews" and self._matches(query, [
                "访谈", "采访", "说", "回答",
            ]):
                boost *= 1.2

            scores[doc_id] *= boost

        # Sort by score descending
        ranked = sorted(scores.items(), key=lambda x: -x[1])

        # Build excerpts, respecting token budget
        results: list[KnowledgeExcerpt] = []
        total_tokens = 0
        for doc_id, _score in ranked:
            doc = self.documents[doc_id]
            text = doc.text

            # Extract the best snippet for this query
            snippet = self._extract_best_snippet(text, query_terms, window_words=200)
            token_count = max(1, len(snippet) // 4)

            if total_tokens + token_count > max_tokens:
                break

            results.append(KnowledgeExcerpt(source=doc.source or doc_id, text=snippet))
            total_tokens += token_count

        return results

    # ── File Loading ────────────────────────────────────────────────

    def load_directory(self, directory: Path | None = None) -> int:
        """
        Scan a directory for Markdown files and index them.
        Returns the number of documents loaded.
        """
        directory = directory or config.KNOWLEDGE_DIR
        if not directory.exists():
            return 0

        count = 0
        for md_file in sorted(directory.rglob("*.md")):
            doc_id = str(md_file.relative_to(directory))
            text = md_file.read_text(encoding="utf-8")

            # Determine category from path
            try:
                relative = md_file.relative_to(directory)
                category = relative.parts[0] if relative.parts else "other"
            except ValueError:
                category = "other"

            # Parse optional metadata from the file
            tags = self._parse_tags(text)

            self.add_document(doc_id, text, category, tags, source=doc_id)
            count += 1

        return count

    # ── Utilities ───────────────────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text into terms (lowercase, no punctuation)."""
        text = text.lower()
        # Split on non-word characters, keep Chinese characters as-is
        terms = re.findall(r'[一-鿿]+|[a-z]+', text)
        # Filter out very short terms (1 char English, keep all Chinese)
        return [t for t in terms if len(t) > 1 or re.match(r'[一-鿿]', t)]

    @staticmethod
    def _count_term(text: str, term: str) -> int:
        """Count occurrences of a term in text (case-insensitive)."""
        return len(re.findall(re.escape(term), text.lower()))

    @staticmethod
    def _matches(text: str, keywords: list[str]) -> bool:
        """Check if any keyword appears in the text."""
        text_lower = text.lower()
        return any(kw in text_lower for kw in keywords)

    @staticmethod
    def _parse_tags(text: str) -> list[str]:
        """Extract tags from metadata section of a Markdown file."""
        tags_match = re.search(r'-\s*tags:\s*(.+)', text)
        if tags_match:
            return [t.strip() for t in tags_match.group(1).split(",")]
        return []

    @staticmethod
    def _extract_best_snippet(text: str, query_terms: list[str],
                              window_words: int = 200) -> str:
        """
        Extract the paragraph/section with the highest concentration
        of query terms.
        """
        # Split into paragraphs
        paragraphs = re.split(r'\n\s*\n', text)
        if not paragraphs:
            return text[:500]

        best_score = -1
        best_paragraph = paragraphs[0]

        for para in paragraphs:
            para_lower = para.lower()
            score = sum(para_lower.count(term) for term in query_terms)
            if score > best_score:
                best_score = score
                best_paragraph = para

        # Truncate if too long
        words = best_paragraph.split()
        if len(words) > window_words:
            best_paragraph = " ".join(words[:window_words]) + "..."

        return best_paragraph

    def get_document_list(self) -> list[dict]:
        """Return a list of all indexed documents with metadata."""
        return [
            {
                "doc_id": doc.doc_id,
                "category": doc.category,
                "word_count": self.doc_lengths.get(doc.doc_id, 0),
                "tags": doc.tags,
                "source": doc.source,
            }
            for doc in self.documents.values()
        ]
