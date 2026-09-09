import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import litellm
from litellm.llms.custom_httpx.http_handler import (
    get_async_httpx_client,
    httpxSpecialProvider,
)
from litellm.proxy.guardrails.guardrail_hooks.zscaler_ai_guard.zscaler_ai_guard import (
    ZscalerAIGuard,
)

_ENDPOINT = "https://api.us1.zseclipse.net/v1/detection/execute-policy"


def _resp(body: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=body,
        request=httpx.Request("POST", _ENDPOINT),
    )


def _allow() -> httpx.Response:
    return _resp({"statusCode": 200, "action": "ALLOW", "transactionId": "tx-1"})


class FakeHandler:
    def __init__(self, items: list[Any]):
        self._items = list(items)
        self.calls: list[SimpleNamespace] = []

    async def post(self, *, url, headers, json, timeout=None):
        self.calls.append(SimpleNamespace(url=url, headers=headers, json=json, timeout=timeout))
        if not self._items:
            raise AssertionError("FakeHandler ran out of programmed responses")
        item = self._items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture(autouse=True)
def _clear_client_cache():
    cache = litellm.in_memory_llm_clients_cache
    cache.cache_dict.clear()
    cache.ttl_dict.clear()
    cache.expiration_heap.clear()
    yield
    cache.cache_dict.clear()
    cache.ttl_dict.clear()
    cache.expiration_heap.clear()


def _expire_client_cache() -> None:
    cache = litellm.in_memory_llm_clients_cache
    for key in list(cache.ttl_dict):
        cache.ttl_dict[key] = time.time() - 1


def _make_guardrail(handler: Any = None) -> ZscalerAIGuard:
    return ZscalerAIGuard(
        api_key="test-key",
        api_base=_ENDPOINT,
        policy_id=1,
        guardrail_name="zscaler-ai-guard",
        async_handler=handler,
    )


def test_uses_guardrail_client_pool_not_logging_pool():
    """
    The hook must share the guardrail connection pool, not the logging pool.
    Landing on the logging pool couples guardrail latency to logging traffic,
    since AIOHTTP_CONNECTOR_LIMIT is a per-connector cap across all hosts.
    """
    guardrail = _make_guardrail()

    assert guardrail.async_handler is get_async_httpx_client(llm_provider=httpxSpecialProvider.GuardrailCallback)
    assert guardrail.async_handler is not get_async_httpx_client(llm_provider=httpxSpecialProvider.LoggingCallback)


@pytest.mark.asyncio
async def test_reuses_one_client_across_requests():
    handler = FakeHandler([_allow(), _allow(), _allow()])
    guardrail = _make_guardrail(handler)

    for _ in range(3):
        await guardrail.make_zscaler_ai_guard_api_call(_ENDPOINT, "test-key", 1, "IN", "hello")

    assert len(handler.calls) == 3


@pytest.mark.asyncio
async def test_client_survives_llm_client_cache_expiry():
    """
    Regression: the hook used to call get_async_httpx_client() inside the
    per-request send path. The client cache has a 1 hour TTL that is not
    refreshed on read, so every expiry handed the hook a brand new client and
    threw away its warm connection pool, forcing fresh TLS handshakes.
    """
    handler = FakeHandler([_allow(), _allow()])
    guardrail = _make_guardrail(handler)

    await guardrail.make_zscaler_ai_guard_api_call(_ENDPOINT, "test-key", 1, "IN", "before")

    _expire_client_cache()
    assert get_async_httpx_client(llm_provider=httpxSpecialProvider.GuardrailCallback) is not handler

    await guardrail.make_zscaler_ai_guard_api_call(_ENDPOINT, "test-key", 1, "IN", "after")

    assert len(handler.calls) == 2, "guardrail rebuilt its client instead of reusing the pooled one"


def test_default_client_is_stable_across_cache_expiry():
    guardrail = _make_guardrail()
    original = guardrail.async_handler

    _expire_client_cache()
    rebuilt = get_async_httpx_client(llm_provider=httpxSpecialProvider.GuardrailCallback)

    assert rebuilt is not original
    assert guardrail.async_handler is original


@pytest.mark.asyncio
async def test_request_carries_configured_timeout_and_payload():
    handler = FakeHandler([_allow()])
    guardrail = _make_guardrail(handler)

    await guardrail.make_zscaler_ai_guard_api_call(_ENDPOINT, "test-key", 7, "OUT", "some content")

    call = handler.calls[0]
    assert call.url == _ENDPOINT
    assert call.timeout == guardrail.timeout
    assert call.json == {"direction": "OUT", "content": "some content", "policyId": 7}
    assert call.headers["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_blocked_content_raises_through_pooled_client():
    blocked = _resp(
        {
            "statusCode": 200,
            "action": "BLOCK",
            "transactionId": "tx-blocked",
            "detectorResponses": {"pii": {"action": "BLOCK"}},
        }
    )
    handler = FakeHandler([blocked])
    guardrail = _make_guardrail(handler)

    with pytest.raises(Exception) as exc_info:
        await guardrail.apply_guardrail(
            inputs={"texts": ["my ssn is 123-45-6789"]},
            request_data={},
            input_type="request",
        )

    assert "Zscaler AI Guard" in str(exc_info.value)
    assert len(handler.calls) == 1
