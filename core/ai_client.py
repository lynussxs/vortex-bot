"""Async OpenRouter chat-completion client."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import aiohttp

MODEL_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{2,127}$")


class AIServiceError(RuntimeError):
    """User-safe AI integration failure."""


class OpenRouterClient:
    def __init__(self, api_key: str | None, default_model: str, max_tokens: int) -> None:
        self.api_key = api_key
        self.default_model = default_model
        self.max_tokens = min(max(1, max_tokens), 8192)
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(3)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=35, connect=8, sock_read=30)
            connector = aiohttp.TCPConnector(limit=8, enable_cleanup_closed=True)
            self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    @staticmethod
    def validate_model(model: str) -> str:
        value = model.strip()
        if not MODEL_PATTERN.fullmatch(value):
            raise ValueError("Model identifiers may contain letters, numbers, dots, underscores, slashes, colons, and hyphens.")
        return value

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.api_key:
            raise AIServiceError("AI is not configured. Add OPENROUTER_API_KEY to the service variables.")
        if self._session is None:
            await self.start()
        assert self._session is not None

        try:
            chosen_model = self.validate_model(model or self.default_model)
        except ValueError as exc:
            raise AIServiceError(str(exc)) from exc
        body: dict[str, Any] = {
            "model": chosen_model,
            "messages": messages,
            "max_tokens": min(max(1, max_tokens or self.max_tokens), self.max_tokens),
            "temperature": 0.4,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://replit.com/",
            "X-Title": "MyBot",
        }
        async with self._semaphore:
            try:
                async with self._session.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=body,
                    headers=headers,
                ) as response:
                    if response.status == 429:
                        raise AIServiceError("The AI service is rate-limiting requests. Please try again shortly.")
                    if response.status in (401, 403):
                        raise AIServiceError("The AI provider rejected its credentials. Check OPENROUTER_API_KEY.")
                    if response.status >= 500:
                        raise AIServiceError("The AI service is temporarily unavailable. Please try again shortly.")
                    payload = await response.json(content_type=None)
                    if response.status >= 400:
                        detail = payload.get("error", {}).get("message", "Request failed")
                        raise AIServiceError(f"The AI request was rejected: {str(detail)[:180]}")
                    choices = payload.get("choices") or []
                    content = choices[0].get("message", {}).get("content") if choices else None
                    if not isinstance(content, str) or not content.strip():
                        raise AIServiceError("The AI service returned an empty response.")
                    return content.strip()[:4000]
            except asyncio.TimeoutError as exc:
                raise AIServiceError("The AI request timed out. Please try again.") from exc
            except aiohttp.ClientError as exc:
                raise AIServiceError("I could not reach the AI service. Please try again later.") from exc
