"""Lop goi AI qua OpenRouter (API tuong thich OpenAI). Doi nha cung cap chi can sua file nay."""
import asyncio
import logging
import os

import aiohttp

log = logging.getLogger("ai")


class AIClient:
    def __init__(self):
        self.key = os.getenv("OPENROUTER_API_KEY")
        self.model = os.getenv("AI_MODEL", "openrouter/auto")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        self.referer = os.getenv("OPENROUTER_REFERER", "https://discord.com")
        self.title = os.getenv("OPENROUTER_TITLE", "Vortex Bot")
        self.last_error = ""
        self._session: aiohttp.ClientSession | None = None
        self._sem = asyncio.Semaphore(3)  # toi da 3 yeu cau AI cung luc
        if not self.key:
            log.warning("Không có OPENROUTER_API_KEY: tính năng AI bị tắt.")

    @property
    def available(self) -> bool:
        return bool(self.key)

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45))
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def chat(self, system, user: str, max_tokens: int = 500, model: str | None = None):
        """Tra ve noi dung tra loi (str) hoac None neu loi (ly do nam trong self.last_error)."""
        if not self.key:
            self.last_error = "chưa có OPENROUTER_API_KEY"
            return None
        if isinstance(system, list):  # chap nhan danh sach khoi {'text': ...}
            system = "\n\n".join(b.get("text", "") for b in system)
        payload = {
            "model": model or self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                   "HTTP-Referer": self.referer, "X-Title": self.title}
        async with self._sem:
            for attempt in range(2):
                try:
                    session = await self._http()
                    async with session.post(f"{self.base_url}/chat/completions", json=payload, headers=headers) as resp:
                        data = await resp.json(content_type=None)
                        status = resp.status
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                    self.last_error = f"{type(e).__name__}: {e}"
                    log.warning("Lỗi gọi OpenRouter: %s", self.last_error)
                    return None
                err = data.get("error") if isinstance(data, dict) else None
                if status == 200 and not err:
                    break
                msg = (err or {}).get("message") if isinstance(err, dict) else str(err or data)[:200]
                self.last_error = f"HTTP {status}: {msg}"[:300]
                if status in (429, 500, 502, 503) and attempt == 0:
                    await asyncio.sleep(2)
                    continue
                log.warning("OpenRouter lỗi: %s", self.last_error)
                return None
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            self.last_error = "phản hồi không đúng định dạng"
            return None
        if isinstance(content, list):  # mot so model tra ve danh sach khoi
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        usage = data.get("usage") or {}
        log.info("AI model=%s tokens in=%s out=%s", payload["model"], usage.get("prompt_tokens"),
                 usage.get("completion_tokens"))
        self.last_error = ""
        return (content or "").strip() or None
