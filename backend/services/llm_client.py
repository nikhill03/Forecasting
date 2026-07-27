"""
backend/services/llm_client.py
================================
Thin async wrapper around Hugging Face's auto-provider Inference router.
Used by the AI Action Center (NL -> operation parsing, Feature 2) and the
Understandability section's explanation/Q&A (Feature 3) — one shared model
per feature-update.md's build decision.
"""

from __future__ import annotations

import httpx
import structlog

from backend.core.config import settings

logger = structlog.get_logger("forecasting.llm_client")

# No provider pinned — confirmed necessary. HF's own first-party "hf-inference"
# provider rejects every commonly-used chat model on the free tier
# ("Model not supported by provider hf-inference"), but this generic
# auto-provider router successfully routes to a third-party backend that
# actually serves settings.LLM_MODEL_ID.
_ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"
_TIMEOUT_SECONDS = 30.0


class LLMClientError(Exception):
    """Raised when the HF router call fails or returns an unusable response.
    Callers must catch this and degrade gracefully (e.g. "AI assistant
    unavailable") — never let it bubble up and crash a request."""


async def chat_completion(
    messages: list[dict[str, str]],
    max_tokens: int = 500,
    temperature: float = 0.2,
) -> str:
    """Sends a chat-completions request and returns the assistant's message
    content. Raises LLMClientError on any failure — timeout, non-2xx,
    missing/expired token, or an unexpected response shape."""
    if not settings.HF_TOKEN:
        raise LLMClientError("HF_TOKEN is not configured")

    payload = {
        "model": settings.LLM_MODEL_ID,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _ROUTER_URL,
                headers={"Authorization": f"Bearer {settings.HF_TOKEN}"},
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise LLMClientError(f"LLM request timed out after {_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise LLMClientError(f"LLM request failed: {exc}") from exc

    if response.status_code != 200:
        logger.warning(
            "llm_request_failed",
            status_code=response.status_code,
            body=response.text[:500],
        )
        raise LLMClientError(
            f"LLM provider returned {response.status_code}: {response.text[:200]}"
        )

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMClientError(f"Unexpected LLM response shape: {data}") from exc
