"""Provider contract tests. No credentials or live network calls are used here."""
import json

import httpx
import pytest

from app.ai import AIClient


@pytest.mark.parametrize("provider,host", [("deepseek", "api.deepseek.com"), ("openai", "api.openai.com")])
async def test_json_request_goes_only_to_selected_provider(monkeypatch, provider, host):
    real_client = httpx.AsyncClient
    requests = []

    def respond(request):
        requests.append(request)
        content = json.dumps(dict(category='SPAM', confidence=.95, intent='other', reason='Prize scam',
                                  evidence=[dict(source='body', quote='Claim your prize now')]))
        if provider == 'openai':
            return httpx.Response(200, json={'status':'completed', 'output':[
                {'type':'reasoning'}, {'type':'message', 'content':[{'type':'output_text', 'text':content}]}]})
        return httpx.Response(200, json={'choices':[{'finish_reason':'stop', 'message':{'content':content}}]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    client = AIClient(provider=provider, api_key="test-secret", model="deepseek-flash" if provider == "deepseek" else "test-model",
                      fallback_model="", max_rpm=0)
    result = await client.classify_email({"subject": "Prize", "body": "Claim your prize now"})
    assert result["category"] == "SPAM"
    assert len(requests) == 1 and requests[0].url.host == host
    assert requests[0].headers["Authorization"] == "Bearer test-secret"
    payload = json.loads(requests[0].content)
    if provider == "deepseek":
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["model"] == "deepseek-flash"
        assert payload["thinking"] == {"type": "disabled"}
    else:
        assert requests[0].url.path == '/v1/responses'
        assert payload['text']['format'] == {'type':'json_object'}
        assert payload['store'] is False
        assert 'temperature' not in payload and 'max_tokens' not in payload
        assert "thinking" not in payload
    assert "test-secret" not in json.dumps(client.describe())


@pytest.mark.parametrize("status", [401, 402])
async def test_auth_or_balance_error_is_visible_without_retry_or_key(monkeypatch, status):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json={"error": {"message": "unavailable"}})), **kwargs))
    client = AIClient(provider="deepseek", api_key="test-secret", model="deepseek-flash", fallback_model="", max_rpm=0)
    assert await client.complete_json("Return JSON", "Test") is None
    assert client.calls == 1 and client.failures == 1
    assert str(status) in client.last_error
    assert "test-secret" not in json.dumps(client.describe())


async def test_truncated_response_is_not_accepted_as_success(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [{
            "finish_reason": "length", "message": {"content": '{"partial":true}'}
        }]})), **kwargs))
    client = AIClient(provider="deepseek", api_key="test-secret", model="deepseek-flash", fallback_model="", max_rpm=0)
    client.retry_base_s = 0
    assert await client.complete_json("Return JSON", "Test") is None
    assert client.calls == 1 and client.failures == 1
