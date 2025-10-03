from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException

from litellm.proxy._types import UserAPIKeyAuth
from litellm.proxy.guardrails.guardrail_hooks.zguard.zguard import (
    ZGuardGuardrail,
)
from litellm.types.utils import Choices, Message, ModelResponse


@pytest.mark.asyncio
async def test_zguard_guardrail_pre_call_hook_blocked():
    zguard_guardrail = ZGuardGuardrail(
        guardrail_name="zguard",
        api_key="test_api_key",
        api_base="https://test.zseclipse.net/v1/detection",
        policy_id=47,
    )

    with patch.object(zguard_guardrail.async_handler, "post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "blocked": True,
            "reason": "Profanity detected",
        }
        mock_response.text = '{"blocked": true, "reason": "Profanity detected"}'
        mock_post.return_value = mock_response

        with pytest.raises(HTTPException) as exc_info:
            await zguard_guardrail.async_moderation_hook(
                user_api_key_dict=UserAPIKeyAuth(api_key="test_api_key"),
                data={
                    "messages": [
                        {
                            "role": "user",
                            "content": "fuck",
                        }
                    ]
                },
                call_type="completion",
            )

        assert exc_info.value.status_code == 400
        assert "Violated guardrail policy" in str(exc_info.value.detail)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert (
            call_kwargs["url"]
            == "https://test.zseclipse.net/v1/detection/execute-policy"
        )
        assert "Authorization" in call_kwargs["headers"]
        assert call_kwargs["headers"]["Authorization"] == "Bearer test_api_key"


@pytest.mark.asyncio
async def test_zguard_guardrail_pre_call_hook_allowed():
    zguard_guardrail = ZGuardGuardrail(
        guardrail_name="zguard",
        api_key="test_api_key",
        api_base="https://test.zseclipse.net/v1/detection",
        policy_id=47,
    )

    with patch.object(zguard_guardrail.async_handler, "post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"blocked": False}
        mock_response.text = '{"blocked": false}'
        mock_post.return_value = mock_response

        result = await zguard_guardrail.async_moderation_hook(
            user_api_key_dict=UserAPIKeyAuth(api_key="test_api_key"),
            data={
                "messages": [
                    {
                        "role": "user",
                        "content": "Hello, how are you?",
                    }
                ]
            },
            call_type="completion",
        )

        assert result is None

        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_zguard_guardrail_post_call_success_hook_blocked():
    zguard_guardrail = ZGuardGuardrail(
        guardrail_name="zguard",
        api_key="test_api_key",
        api_base="https://test.zseclipse.net/v1/detection",
        policy_id=47,
    )

    with patch.object(zguard_guardrail.async_handler, "post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "blocked": True,
            "reason": "Inappropriate content",
        }
        mock_response.text = '{"blocked": true, "reason": "Inappropriate content"}'
        mock_post.return_value = mock_response

        with pytest.raises(HTTPException) as exc_info:
            await zguard_guardrail.async_post_call_success_hook(
                data={},
                user_api_key_dict=UserAPIKeyAuth(api_key="test_api_key"),
                response=ModelResponse(
                    choices=[
                        Choices(
                            index=0,
                            message=Message(content="This is inappropriate content!"),
                        )
                    ]
                ),
            )

        assert exc_info.value.status_code == 400
        assert "Violated guardrail policy" in str(exc_info.value.detail)

        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_zguard_guardrail_post_call_success_hook_allowed():
    zguard_guardrail = ZGuardGuardrail(
        guardrail_name="zguard",
        api_key="test_api_key",
        api_base="https://test.zseclipse.net/v1/detection",
        policy_id=47,
    )

    with patch.object(zguard_guardrail.async_handler, "post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"blocked": False}
        mock_response.text = '{"blocked": false}'
        mock_post.return_value = mock_response

        result = await zguard_guardrail.async_post_call_success_hook(
            data={},
            user_api_key_dict=UserAPIKeyAuth(api_key="test_api_key"),
            response=ModelResponse(
                choices=[
                    Choices(
                        index=0,
                        message=Message(content="This is appropriate content."),
                    )
                ]
            ),
        )

        assert result is None

        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_zguard_extract_text_from_messages():
    zguard_guardrail = ZGuardGuardrail(
        guardrail_name="zguard",
        api_key="test_api_key",
        policy_id=47,
    )

    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": [{"type": "text", "text": "How are you?"}]},
    ]

    result = zguard_guardrail.extract_text_from_messages(messages)
    assert result == "Hello Hi there How are you?"


@pytest.mark.asyncio
async def test_zguard_initialization_missing_api_key():
    with pytest.raises(ValueError) as exc_info:
        ZGuardGuardrail(
            guardrail_name="zguard",
            policy_id=47,
        )

    assert "API key is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_zguard_initialization_missing_policy_id():
    with pytest.raises(ValueError) as exc_info:
        ZGuardGuardrail(
            guardrail_name="zguard",
            api_key="test_api_key",
        )

    assert "policy ID is required" in str(exc_info.value)
