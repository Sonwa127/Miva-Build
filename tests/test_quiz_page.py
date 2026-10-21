"""Quiz generation from messy AI replies. Needs the line-break fix in archive/jsonparse.py."""
import pytest

from archive import config


class FakeStore:
    def list_chunks(self, doc_id):
        return [(1, 0, "", "A set is a collection of distinct objects."), (2, 0, "", "A function maps each input to one output.")]


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, user, temperature=0.1, max_tokens=600):
        return self.reply


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DB", tmp_path / "app.sqlite")
    return tmp_path


def test_quiz_is_made_from_a_reply_with_line_breaks_and_junk_is_refused(db, monkeypatch):
    import pytest as _pytest
    from archive import quizzes
    from archive.llm import LLMError
    monkeypatch.setattr(quizzes, "DB_PATH", db / "quizzes.sqlite")
    reply = ('```json\n[{"question": "What is a set?", "choices": ["A collection\nof objects", "A number", "A line", "A graph"],'
             ' "correct_index": 0, "explanation": "By definition.\nSee page 1.", "page": 1}]\n```')
    quiz = quizzes.generate_quiz("doc1", FakeStore(), FakeLLM(reply), course_id="MTH 101", num_questions=1)
    assert quiz.question_count == 1 and quiz.questions[0].correct_index == 0
    result = quizzes.submit_quiz(quiz.id, [0])
    assert result.score == 1 and result.total == 1
    before = len(quizzes.list_quizzes())
    with _pytest.raises(LLMError):
        quizzes.generate_quiz("doc1", FakeStore(), FakeLLM("I cannot do that."), course_id="MTH 101")
    assert len(quizzes.list_quizzes()) == before          # nothing was published
