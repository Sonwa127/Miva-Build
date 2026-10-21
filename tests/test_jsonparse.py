"""Reading JSON lists from messy model replies, and flashcard generation that no longer silently makes nothing."""
import pytest

from archive import config, flashcards
from archive.jsonparse import parse_json_list


def test_clean_fenced_and_chatty_replies():
    assert parse_json_list('[{"question":"a","answer":"b"}]') == [{"question": "a", "answer": "b"}]
    fenced = '```json\n[\n {"question": "a", "answer": "b", "page": 1}\n]\n```'
    assert parse_json_list(fenced)[0]["page"] == 1
    assert parse_json_list('Here you go:\n[{"x": 1}]\nHope that helps!') == [{"x": 1}]


def test_a_reply_cut_off_in_the_middle_keeps_the_complete_cards():
    cut = '[{"question":"one","answer":"1"},{"question":"two","answer":"2"},{"question":"thr'
    assert [c["question"] for c in parse_json_list(cut)] == ["one", "two"]
    assert parse_json_list('```json\n[{"a": "x {brace}"}, {"a": "y') == [{"a": "x {brace}"}]


def test_nothing_readable_gives_an_empty_list():
    assert parse_json_list("") == [] and parse_json_list(None) == []
    assert parse_json_list("Sorry, I cannot help with that.") == []
    assert parse_json_list('{"not": "a list"}') == []


class FakeStore:
    def list_chunks(self, doc_id):
        return [(1, 0, "", "A set is a collection of distinct objects."), (2, 0, "", "A function maps each input to one output.")]


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.max_tokens = reply, None

    def complete(self, system, user, temperature=0.1, max_tokens=600):
        self.max_tokens = max_tokens
        return self.reply


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DB", tmp_path / "app.sqlite")
    monkeypatch.setattr(flashcards, "DB_PATH", config.APP_DB, raising=False)
    return tmp_path


def test_truncated_reply_still_makes_the_cards_that_arrived(db):
    reply = '```json\n[{"question":"What is a set?","answer":"A collection of distinct objects","page":1},{"question":"What is a func'
    llm = FakeLLM(reply)
    cards = flashcards.generate_flashcards("doc1", FakeStore(), llm, course_id="MTH 101")
    assert [c.question for c in cards] == ["What is a set?"] and llm.max_tokens >= 3000


def test_bad_page_number_does_not_lose_the_card(db):
    cards = flashcards.generate_flashcards("doc1", FakeStore(), FakeLLM('[{"question":"q","answer":"a","page":"n/a"}]'), course_id="MTH 101")
    assert len(cards) == 1 and cards[0].page == 1


def test_line_breaks_inside_answers_are_accepted():
    """Real Mistral replies put actual newlines inside the answer text, which strict JSON rejects."""
    reply = ('[\n {"question": "Steps?", "answer": "The steps:\n  1. Define\n  2. Collect", "page": 33},\n'
             ' {"question": "Two?", "answer": "A\nB", "page": 34}\n]')
    cards = parse_json_list(reply)
    assert [c["page"] for c in cards] == [33, 34] and "1. Define" in cards[0]["answer"]
    cut = '```json\n[{"question": "q1", "answer": "a\nb", "page": 1}, {"question": "q2", "answer": "a\nb'
    assert [c["question"] for c in parse_json_list(cut)] == ["q1"]


def test_summary_with_line_breaks_is_read_and_junk_is_refused(db, monkeypatch):
    import pytest as _pytest
    from archive import summaries
    monkeypatch.setattr(summaries, "DB_PATH", db / "summaries.sqlite")
    from archive.llm import LLMError
    good = FakeLLM('```json\n{"title": "T", "summary_text": "Line one\nLine two", "key_concepts": ["a"], "source_pages": [1]}\n```')
    result = summaries.generate_summary("doc1", FakeStore(), good, course_id="MTH 101")
    assert "Line two" in result.summary_text
    with _pytest.raises(LLMError):
        summaries.generate_summary("doc1", FakeStore(), FakeLLM("Sorry, I cannot do that."), course_id="MTH 101")
