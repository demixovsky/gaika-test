from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

from app.database import Database


@dataclass(frozen=True, slots=True)
class FAQEntry:
    section: str
    question: str
    answer: str


@dataclass(frozen=True, slots=True)
class FAQSearchResult:
    section: str
    question: str
    answer: str
    score: float

    def to_dict(self) -> dict[str, str | float]:
        return asdict(self)


QUESTION_RE = re.compile(r"^\*\*(.+?)\*\*\s*$")
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return " ".join(TOKEN_RE.findall(normalized))


def parse_faq(text: str) -> list[FAQEntry]:
    entries: list[FAQEntry] = []
    section = ""
    question: str | None = None
    answer_lines: list[str] = []

    def flush() -> None:
        nonlocal question, answer_lines
        answer = "\n".join(answer_lines).strip()
        if section and question and answer:
            entries.append(FAQEntry(section, question, answer))
        question = None
        answer_lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            flush()
            section = line[3:].strip()
            continue
        question_match = QUESTION_RE.match(line)
        if question_match:
            flush()
            question = question_match.group(1).strip()
            continue
        if question is not None:
            if line:
                answer_lines.append(line)
            elif answer_lines and answer_lines[-1] != "":
                answer_lines.append("")
    flush()
    return entries


def load_faq(path: Path) -> list[FAQEntry]:
    return parse_faq(path.read_text(encoding="utf-8"))


class FAQRepository:
    def __init__(self, database: Database, fuzzy_threshold: float = 58.0) -> None:
        self.database = database
        self.fuzzy_threshold = fuzzy_threshold
        self._entries: list[FAQEntry] = []

    async def rebuild(self, entries: list[FAQEntry]) -> None:
        connection = await self.database.connect()
        try:
            await connection.execute("DELETE FROM faq_fts")
            await connection.executemany(
                "INSERT INTO faq_fts(section, question, answer) VALUES (?, ?, ?)",
                [(entry.section, entry.question, entry.answer) for entry in entries],
            )
            await connection.commit()
        finally:
            await connection.close()
        self._entries = list(entries)

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = normalize_text(query).split()
        return " OR ".join(f'"{token}"*' for token in tokens[:12])

    async def search_faq(self, query: str, limit: int = 3) -> list[FAQSearchResult]:
        fts_query = self._fts_query(query)
        if not fts_query:
            return []

        connection = await self.database.connect()
        try:
            cursor = await connection.execute(
                """
                SELECT section, question, answer,
                       bm25(faq_fts, 1.0, 5.0, 1.0) AS rank
                FROM faq_fts
                WHERE faq_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            )
            rows = await cursor.fetchall()
        finally:
            await connection.close()

        if rows:
            return [
                FAQSearchResult(
                    section=row["section"],
                    question=row["question"],
                    answer=row["answer"],
                    score=round(1.0 / (1.0 + abs(float(row["rank"]))), 4),
                )
                for row in rows
            ]
        return self._fuzzy_search(query, limit)

    def _fuzzy_search(self, query: str, limit: int) -> list[FAQSearchResult]:
        normalized_query = normalize_text(query)
        choices = {
            index: normalize_text(
                f"{entry.question} {entry.section} {entry.answer}"
            )
            for index, entry in enumerate(self._entries)
        }
        matches = process.extract(
            normalized_query,
            choices,
            scorer=fuzz.WRatio,
            limit=limit,
            score_cutoff=self.fuzzy_threshold,
        )
        results: list[FAQSearchResult] = []
        for _, score, index in matches:
            entry = self._entries[index]
            results.append(
                FAQSearchResult(
                    entry.section,
                    entry.question,
                    entry.answer,
                    round(score / 100.0, 4),
                )
            )
        return results
