from pathlib import Path

import pytest

from app.database import Database
from app.faq import FAQRepository, load_faq, parse_faq


def test_parser_supports_sections_and_multiline_answers() -> None:
    text = """
# Header
## Раздел
**Первый вопрос?**
Первая строка.
Вторая строка.

**Второй вопрос?**
Последний ответ.
"""
    entries = parse_faq(text)
    assert len(entries) == 2
    assert entries[0].section == "Раздел"
    assert entries[0].question == "Первый вопрос?"
    assert entries[0].answer == "Первая строка.\nВторая строка."
    assert entries[1].answer == "Последний ответ."


def test_parser_ignores_incomplete_fragments() -> None:
    entries = parse_faq("**Без раздела?**\nОтвет\n## Раздел\n**Без ответа?**")
    assert entries == []


@pytest.fixture
async def faq_repository(tmp_path: Path) -> FAQRepository:
    database = Database(tmp_path / "test.db")
    await database.initialize()
    repository = FAQRepository(database)
    entries = load_faq(Path("data/faq.md"))
    await repository.rebuild(entries)
    return repository


@pytest.mark.parametrize(
    ("query", "expected_question"),
    [
        ("шиномонтаж R18", "Сколько стоит шиномонтаж?"),
        ("ремонт АКПП", "Ремонтируете ли вы коробки передач?"),
        ("свои детали запчасти", "Можно привезти свои запчасти?"),
    ],
)
async def test_search_finds_expected_entry(
    faq_repository: FAQRepository, query: str, expected_question: str
) -> None:
    results = await faq_repository.search_faq(query)
    assert results
    assert results[0].question == expected_question
    assert len(results) <= 3
    assert 0 <= results[0].score <= 1


async def test_unknown_query_returns_empty(faq_repository: FAQRepository) -> None:
    results = await faq_repository.search_faq("квантовый телепортатор антиматерии")
    assert results == []

