"""Follow-up questions such as 'Give examples' must keep the topic of the question before them."""
from types import SimpleNamespace

from archive import qa


def hit(text, page=1):
    return SimpleNamespace(score=0.9, citation=f"Notes p.{page}", title="Notes", page=page, doc_id="d", text=text)


class FakeStore:
    def __init__(self):
        self.queries = []

    def count(self):
        return 1

    def search(self, query, k, course=None, doc_id=None):
        self.queries.append(query)
        return [hit("A linear equation has the form ax + b = 0.")]


class FakeLLM:
    def __init__(self):
        self.prompt = None

    def complete(self, system, user, **kwargs):
        self.prompt = user
        return "Example: 2x + 3 = 7 [1]"


def test_which_questions_count_as_follow_ups():
    previous = "Linear Equations"
    for question in ["Give examples", "Explain more", "why is that?", "Show the steps", "what about the second one"]:
        assert qa.is_follow_up(question, previous), question
    for question in ["What is a set?", "Define the union of two sets", "How do I find the median of a list of numbers in statistics"]:
        assert not qa.is_follow_up(question, previous), question
    assert not qa.is_follow_up("Give examples", None) and not qa.is_follow_up("Give examples", "   ")


def test_a_follow_up_is_searched_together_with_the_earlier_topic():
    store, llm = FakeStore(), FakeLLM()
    qa.answer_question("Give examples", store, llm, course="MTH 101", previous="Linear Equations")
    assert store.queries == ["Linear Equations Give examples"]
    assert "EARLIER QUESTION (for context only): Linear Equations" in llm.prompt and llm.prompt.endswith("QUESTION: Give examples")


def test_a_fresh_question_ignores_the_earlier_one():
    store, llm = FakeStore(), FakeLLM()
    qa.answer_question("What is the union of two sets?", store, llm, previous="Linear Equations")
    assert store.queries == ["What is the union of two sets?"] and "EARLIER QUESTION" not in llm.prompt


def test_no_earlier_question_behaves_as_before():
    store, llm = FakeStore(), FakeLLM()
    qa.answer_question("Give examples", store, llm)
    assert store.queries == ["Give examples"] and "EARLIER QUESTION" not in llm.prompt


def test_a_very_long_earlier_question_is_trimmed():
    store, llm = FakeStore(), FakeLLM()
    qa.answer_question("Give examples", store, llm, previous="x " * 400)
    assert len(store.queries[0]) <= 300 + len(" Give examples")
