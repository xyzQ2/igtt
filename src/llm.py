"""One LLM client for the whole project, whichever provider config.yaml names.

Every call site was written against the Anthropic SDK (`client.messages.create`
returning `.content[i].text`). Rather than touch each one, OpenAI and Google get a
small shim with that same shape, and image blocks in Anthropic's base64 format are
translated per provider.
"""

import base64
import os
from types import SimpleNamespace

import requests
from anthropic import Anthropic
from google import genai
from google.genai import types as genai_types

PROVIDERS = ("anthropic", "openai", "google")

KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
}

# Used when config.yaml leaves a model blank, so switching provider is one setting.
DEFAULT_MODELS = {
    "anthropic": {"text_analysis": "claude-haiku-4-5-20251001",
                  "strategy": "claude-sonnet-5"},
    "openai": {"text_analysis": "gpt-5-mini", "strategy": "gpt-5"},
    "google": {"text_analysis": "gemini-2.5-flash", "strategy": "gemini-2.5-pro"},
}

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
TIMEOUT = 300


def resolve_models(models: dict) -> dict:
    """Fill blank text_analysis/strategy with the provider's defaults."""
    provider = models.get("provider") or "anthropic"
    if provider not in PROVIDERS:
        raise ValueError(f"models.provider must be one of {PROVIDERS}, got {provider!r}")
    filled = {k: v for k, v in models.items() if v}
    return {**DEFAULT_MODELS[provider], **filled, "provider": provider}


def client(models: dict):
    """A client with Anthropic's `messages.create` shape for the configured provider."""
    provider = models.get("provider") or "anthropic"
    key = os.environ.get(KEY_ENV[provider], "")
    if provider == "anthropic":
        return Anthropic(api_key=key)
    return _Shim(provider, key)


def _parts(messages: list) -> list:
    """The single user message's content as a list of Anthropic-style blocks."""
    content = messages[0]["content"]
    return content if isinstance(content, list) else [{"type": "text", "text": content}]


class _Shim:
    def __init__(self, provider: str, key: str):
        self.provider, self.key = provider, key
        self.messages = self

    def create(self, model: str, max_tokens: int, messages: list):
        call = self._openai if self.provider == "openai" else self._google
        text = call(model, max_tokens, _parts(messages))
        return SimpleNamespace(content=[SimpleNamespace(text=text or "")])

    def _openai(self, model, max_tokens, parts):
        content = []
        for p in parts:
            if p["type"] == "image":
                src = p["source"]
                content.append({"type": "image_url", "image_url": {
                    "url": f"data:{src['media_type']};base64,{src['data']}"}})
            else:
                content.append({"type": "text", "text": p["text"]})
        # Reasoning models count thinking against this limit, like Claude's.
        resp = requests.post(OPENAI_URL, timeout=TIMEOUT,
                             headers={"Authorization": f"Bearer {self.key}"},
                             json={"model": model, "max_completion_tokens": max_tokens,
                                   "messages": [{"role": "user", "content": content}]})
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _google(self, model, max_tokens, parts):
        contents = []
        for p in parts:
            if p["type"] == "image":
                src = p["source"]
                contents.append(genai_types.Part.from_bytes(
                    data=base64.b64decode(src["data"]), mime_type=src["media_type"]))
            else:
                contents.append(p["text"])
        result = genai.Client(api_key=self.key).models.generate_content(
            model=model, contents=contents,
            config=genai_types.GenerateContentConfig(max_output_tokens=max_tokens))
        return result.text
