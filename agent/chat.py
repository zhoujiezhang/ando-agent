"""
LLM API interaction with streaming support.

Uses OpenAI-compatible API to call Qwen (通义千问) via DashScope.
Yields response chunks as they arrive for SSE streaming.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

import config


class ChatError(Exception):
    """Raised when the LLM API call fails."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _make_client() -> AsyncOpenAI:
    """Create an authenticated AsyncOpenAI client pointing to DashScope."""
    if not config.QWEN_API_KEY:
        raise ChatError(
            "QWEN_API_KEY not set. Copy .env.example to .env and add your DashScope API key.",
        )
    return AsyncOpenAI(
        api_key=config.QWEN_API_KEY,
        base_url=config.QWEN_BASE_URL,
    )


async def stream_chat(
    messages: list[dict[str, str]],
    system_prompt: str,
    model: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Call Qwen API via OpenAI-compatible endpoint and yield text chunks.

    Args:
        messages: List of {role, content} dicts (user/assistant only).
        system_prompt: The full system prompt string.
        model: Optional model override (defaults to config.DEFAULT_MODEL).

    Yields:
        Text chunks from the assistant's response.
    """
    client = _make_client()
    model_name = model or config.DEFAULT_MODEL

    # Insert system prompt as the first message
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    try:
        stream = await client.chat.completions.create(
            model=model_name,
            messages=full_messages,
            max_tokens=config.MAX_RESPONSE_TOKENS,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        raise ChatError(str(exc), status_code) from exc


async def get_full_response(
    messages: list[dict[str, str]],
    system_prompt: str,
    model: str | None = None,
) -> str:
    """
    Call Qwen API and return the complete response as a single string.

    Used for non-streaming contexts (e.g., knowledge retrieval testing).
    """
    client = _make_client()
    model_name = model or config.DEFAULT_MODEL

    full_messages = [{"role": "system", "content": system_prompt}] + messages

    response = await client.chat.completions.create(
        model=model_name,
        messages=full_messages,
        max_tokens=config.MAX_RESPONSE_TOKENS,
    )

    return response.choices[0].message.content or ""
