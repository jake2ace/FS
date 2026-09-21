"""The AI client must fall back to a second model when the primary is overloaded, and rest the primary."""
import httpx
import pytest

import asyncio
import time

from app.ai import AIClient, _Pacer

GOOD = '{"category": "SPAM", "confidence": 0.9, "reason": "r", "intent": "other"}'


class FakeAI(AIClient):
    def __init__(self, fallback: str, primary_status: int = 503):
        super().__init__(provider="gemini", api_key="test-key", model="primary", mode="full", fallback_model=fallback)
        self.retry_base_s = 0.0
        self.max_rpm = 0.0
        self.primary_status = primary_status
        self.seen: list[str] = []

    async def _call(self, system, user, max_tokens, model=None):
        model = model or self.model
        self.seen.append(model)
        if model == "primary":
            req = httpx.Request("POST", "https://example.invalid")
            raise httpx.HTTPStatusError("boom", request=req, response=httpx.Response(self.primary_status, request=req))
        return GOOD


async def test_overloaded_primary_switches_to_fallback_and_rests():
    ai = FakeAI(fallback="backup")
    obj = await ai.complete_json("s", "u")
    assert obj and obj["category"] == "SPAM"
    assert ai.seen == ["primary", "backup"]
    assert ai.fallback_calls == 1 and ai.failures == 1
    # the primary is now resting: the next call goes straight to the fallback
    await ai.complete_json("s", "u")
    assert ai.seen[-1] == "backup" and ai.seen.count("primary") == 1
    assert ai.describe()["primary_resting"] is True


async def test_no_fallback_configured_keeps_retrying_primary_then_gives_up():
    ai = FakeAI(fallback="")
    assert await ai.complete_json("s", "u") is None
    assert ai.seen == ["primary", "primary", "primary"]
    assert ai.fallback_calls == 0 and ai.describe()["fallback_model"] is None


async def test_non_retryable_error_does_not_fall_back():
    ai = FakeAI(fallback="backup", primary_status=400)
    assert await ai.complete_json("s", "u") is None
    assert ai.seen == ["primary"]


def test_fallback_equal_to_primary_is_dropped():
    ai = AIClient(provider="gemini", api_key="k", model="m", mode="full", fallback_model="m")
    assert ai.fallback_model == ""


async def test_pacer_limits_call_starts_per_window():
    pacer = _Pacer(rpm=2, window_s=0.3)
    t0 = time.monotonic()
    await asyncio.gather(pacer.wait(), pacer.wait())
    assert time.monotonic() - t0 < 0.1          # first two are immediate
    await pacer.wait()                           # third must wait for the window
    assert time.monotonic() - t0 >= 0.25
    assert _Pacer(rpm=0).rpm == 0 and await _Pacer(rpm=0).wait() is None   # 0 = unpaced
