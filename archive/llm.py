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


def get_llm(provider: str | None = None, model: str | None = None) -> ChatCompletionsLLM:
    provider = (provider or config.LLM_PROVIDER).lower()
    preset = PROVIDERS.get(provider)
    if preset is None:
        raise LLMError(f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}.")

    key = None
    if preset["key_env"]:
        key = os.getenv(preset["key_env"])
        if not key:
            raise LLMError(
                f"No {preset['key_env']} found. Create a file named .env in the project folder "
                f"(next to cli.py) containing this line:\n  {preset['key_env']}=your-key-here"
            )
    return ChatCompletionsLLM(preset["base_url"], model or config.LLM_MODEL or preset["model"], key)
