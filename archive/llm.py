"""Talk to a chat model.

One small class covers Mistral, OpenAI and Ollama, because all three accept the same
"chat completions" request. Switching provider is a setting, not a code change.
"""
import os

import httpx

from . import config


class LLMError(Exception):
    """A problem with the AI service, worded so a student can act on it."""


PROVIDERS = {
    "mistral": {"base_url": "https://api.mistral.ai/v1", "key_env": "MISTRAL_API_KEY",
                "model": "mistral-small-latest"},
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY",
               "model": "gpt-4o-mini"},
    "ollama": {"base_url": "http://localhost:11434/v1", "key_env": None,
               "model": "llama3.1"},
}


class ChatCompletionsLLM:
    def __init__(self, base_url: str, model: str, api_key: str | None = None,
                 timeout: float = 60.0, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._key = api_key
        self._client = client or httpx.Client(timeout=timeout)

    def _detail(self, r: httpx.Response) -> str:
        """The service explains errors in the reply body. Show that text, minus our key."""
        try:
            data = r.json()
        except ValueError:
            data = None
        msg = None
        if isinstance(data, dict):
            err = data.get("error")
            msg = (err.get("message") if isinstance(err, dict) else err) \
                or data.get("message") or data.get("detail")
        elif data is None:
            msg = r.text
        msg = " ".join(str(msg or "").split())
        if self._key:
            msg = msg.replace(self._key, "***")
        return msg[:300]

    def complete(self, system: str, user: str, temperature: float = 0.1,
                 max_tokens: int = 600) -> str:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            r = self._client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
        except httpx.TimeoutException:
            raise LLMError("The AI service took too long to answer. Try again in a moment.") from None
        except httpx.HTTPError as e:
            raise LLMError(f"Could not reach the AI service ({type(e).__name__}). "
                           "Check your internet connection.") from None

        if r.status_code >= 400:
            detail = self._detail(r)
            note = f"\nMessage from the AI service: {detail}" if detail else ""
            if r.status_code in (401, 403):
                raise LLMError("The AI service rejected the API key. Check the key in your .env file."
                               + note)
            if r.status_code == 429:
                raise LLMError("The AI service says you hit a rate limit or ran out of credit. "
                               "Wait a bit, or check the credit on your account." + note)
            raise LLMError(f"The AI service returned an error (HTTP {r.status_code})." + note)

        try:
            content = r.json()["choices"][0]["message"]["content"]
            if isinstance(content, list):                       # some models return text parts
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            return content.strip()
        except (KeyError, IndexError, ValueError, AttributeError, TypeError):
            raise LLMError("The AI service sent a reply in a format we did not expect.") from None


class OfflineLLM:
    """Offline deterministic LLM emulator for offline development and testing without external cloud credentials."""

    def __init__(self, model: str = "offline-local"):
        self.model = model

    def complete(self, system: str, user: str, temperature: float = 0.1, max_tokens: int = 600) -> str:
        import json
        import re
        sys_lower = system.lower()
        user_lower = user.lower()

        # Flashcards generation
        if "flashcard" in sys_lower or "active-recall" in sys_lower:
            lines = [line.strip() for line in user.splitlines() if len(line.strip()) > 20]
            cards = []
            for i, line in enumerate(lines[:5], 1):
                clean_text = re.sub(r'\[.*?\]', '', line).strip()
                cards.append({
                    "question": f"Explain the key concept in: {clean_text[:60]}...",
                    "answer": clean_text[:200],
                    "page": i
                })
            if not cards:
                cards = [
                    {"question": "What is the primary theorem or principle in this material?", "answer": "The material establishes core algorithmic and conceptual guarantees for optimal performance.", "page": 1}
                ]
            return json.dumps(cards)

        # Quizzes generation
        if "quiz" in sys_lower or "multiple-choice" in sys_lower:
            quiz_qs = [
                {
                    "question": "Which of the following best describes the asymptotic complexity guarantee in this unit?",
                    "choices": ["O(log n) worst-case", "O(n^2) average-case", "O(1) unbounded", "O(n!) non-deterministic"],
                    "answer": "O(log n) worst-case",
                    "explanation": "Balanced search trees and divide-and-conquer structures maintain logarithmic worst-case bounds.",
                    "source_page": 1
                },
                {
                    "question": "Under what condition is a recoloring phase applied rather than a rotation?",
                    "choices": ["When the uncle node is RED", "When the tree height is zero", "When the root is deleted", "When leaf nodes are distinct"],
                    "answer": "When the uncle node is RED",
                    "explanation": "If the uncle is RED, Property 4 violations are resolved strictly by color inversion without tree rotations.",
                    "source_page": 2
                }
            ]
            return json.dumps(quiz_qs)

        # Summaries generation
        if "summary" in sys_lower or "chapter digest" in sys_lower:
            return json.dumps({
                "title": "Comprehensive Lecture Digest",
                "summary": "This lecture covers foundational invariants, structural balancing techniques, and algorithmic analysis. Students master asymptotic tradeoffs and core proof techniques.",
                "key_concepts": ["Balanced Trees", "Invariant Maintenance", "Asymptotic Analysis", "Divide & Conquer"]
            })

        # Glossary generation
        if "glossary" in sys_lower or "term" in sys_lower:
            return json.dumps([
                {"term": "Black-Height", "definition": "The number of black nodes on any simple path from a node to descendant leaves.", "source_page": 1},
                {"term": "Rotation", "definition": "A local operation in a binary search tree that preserves in-order key traversal while altering height.", "source_page": 2}
            ])

        # Semantic answer evaluation & boilerplate detection
        if "evaluate" in sys_lower or "grade" in sys_lower or "rubric" in sys_lower:
            is_boilerplate = any(w in user_lower for w in ["delve", "testament", "tapestry", "in summary,", "it is important to note"])
            return json.dumps({
                "overall_score": 8.5,
                "rubric_breakdown": {"Accuracy": 9.0, "Clarity": 8.0, "Depth": 8.5},
                "missing_concepts": ["Edge cases involving degenerate trees"],
                "is_ai_boilerplate": is_boilerplate,
                "boilerplate_signals": ["Common repetitive synthetic transition detected"] if is_boilerplate else [],
                "feedback": "Strong conceptual understanding demonstrated. Well-reasoned explanation matching the course syllabus."
            })

        # Standard Q&A
        return (
            "Based on the retrieved course material, this topic is explained by the "
            "definitions and examples in the cited excerpt [1]. Review that page for the "
            "exact wording and apply the stated steps or invariant to the question."
        )


def get_llm(provider: str | None = None, model: str | None = None):
    provider = (provider or config.LLM_PROVIDER).lower()
    if provider == "offline":
        return OfflineLLM()

    preset = PROVIDERS.get(provider)
    if preset is None:
        raise LLMError(f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}, offline.")

    key = None
    if preset["key_env"]:
        key = os.getenv(preset["key_env"])
        if not key:
            raise LLMError(
                f"No {preset['key_env']} found. Create a file named .env in the project folder "
                f"(next to cli.py) containing this line:\n  {preset['key_env']}=your-key-here"
            )
    return ChatCompletionsLLM(preset["base_url"], model or config.LLM_MODEL or preset["model"], key)
