"""Lop goi AI (Claude qua Anthropic API). Doi nha cung cap chi can sua file nay."""
import asyncio
import logging
import os

log = logging.getLogger("ai")


class AIClient:
    def __init__(self):
        self.model = os.getenv("AI_MODEL", "claude-haiku-5-5")
        self.client = None
        key = os.getenv("ANTHROPIC_API_KEY")
        if key:
            try:
                import anthropic

                self.client = anthropic.AsyncAnthropic(api_key=key, timeout=40.0, max_retries=2)
            except ImportError:
                log.error("Chưa cài thư viện 'anthropic' (pip install anthropic).")
        else:
            log.warning("Không có ANTHROPIC_API_KEY: tính năng AI bị tắt.")
        self._sem = asyncio.Semaphore(3)  # toi da 3 yeu cau AI cung luc

    @property
    def available(self) -> bool:
        return self.client is not None

    async def chat(self, system, user: str, max_tokens: int = 500):
        """system: chuoi hoac list khoi {'type':'text','text':..., 'cache_control':...}. Loi thi tra None."""
        if not self.client:
            return None
        async with self._sem:
            try:
                resp = await self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
            except Exception as e:  # noqa: BLE001
                log.warning("Lỗi gọi AI: %s: %s", type(e).__name__, e)
                return None
        usage = getattr(resp, "usage", None)
        if usage:
            log.info("AI tokens in=%s out=%s cache_read=%s", usage.input_tokens, usage.output_tokens,
                     getattr(usage, "cache_read_input_tokens", 0))
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip() or None
