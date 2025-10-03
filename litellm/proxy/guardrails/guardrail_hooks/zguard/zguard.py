import os
import sys

sys.path.insert(0, os.path.abspath("../.."))
import json
from typing import TYPE_CHECKING, List, Literal, Optional, Type

from fastapi import HTTPException

from litellm._logging import verbose_proxy_logger
from litellm.integrations.custom_guardrail import (
    CustomGuardrail,
    log_guardrail_information,
)
from litellm.litellm_core_utils.logging_utils import (
    convert_litellm_response_object_to_str,
)
from litellm.llms.custom_httpx.http_handler import (
    get_async_httpx_client,
    httpxSpecialProvider,
)
from litellm.proxy._types import UserAPIKeyAuth
from litellm.types.guardrails import GuardrailEventHooks

GUARDRAIL_NAME = "zguard"

if TYPE_CHECKING:
    from litellm.types.proxy.guardrails.guardrail_hooks.base import GuardrailConfigModel


class ZGuardGuardrail(CustomGuardrail):
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        policy_id: Optional[int] = None,
        **kwargs,
    ):
        self.async_handler = get_async_httpx_client(
            llm_provider=httpxSpecialProvider.GuardrailCallback
        )
        self.zguard_api_key = api_key or os.environ.get("ZGUARD_API_KEY")
        self.zguard_api_base = (
            api_base
            or os.environ.get("ZGUARD_API_BASE")
            or "https://zseclipse.net/v1/detection"
        )
        self.policy_id = policy_id or os.environ.get("ZGUARD_POLICY_ID")

        if not self.zguard_api_key:
            raise ValueError(
                "ZGuard API key is required. Set ZGUARD_API_KEY environment variable or pass api_key parameter."
            )
        if not self.policy_id:
            raise ValueError(
                "ZGuard policy ID is required. Set ZGUARD_POLICY_ID environment variable or pass policy_id parameter."
            )

        try:
            self.policy_id = int(self.policy_id)
        except (TypeError, ValueError):
            raise ValueError(
                f"ZGuard policy_id must be an integer, got: {self.policy_id}"
            )

        super().__init__(**kwargs)

    def extract_text_from_messages(self, messages: List[dict]) -> str:
        text_parts = []
        for message in messages:
            if isinstance(message, dict):
                content = message.get("content", "")
                if isinstance(content, str):
                    text_parts.append(content)
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
        return " ".join(text_parts)

    async def make_zguard_api_request(
        self,
        content: str,
        direction: Literal["IN", "OUT"],
        request_data: dict,
    ):
        data = {
            "policyId": self.policy_id,
            "direction": direction,
            "content": content,
        }

        data.update(
            self.get_guardrail_dynamic_request_body_params(request_data=request_data)
        )

        _json_data = json.dumps(data)

        verbose_proxy_logger.debug(f"ZGuard API request: {data}")

        response = await self.async_handler.post(
            url=f"{self.zguard_api_base}/execute-policy",
            data=_json_data,
            headers={
                "Authorization": f"Bearer {self.zguard_api_key}",
                "Content-Type": "application/json",
            },
        )

        verbose_proxy_logger.debug(
            f"ZGuard API response status: {response.status_code}"
        )
        verbose_proxy_logger.debug(f"ZGuard API response: {response.text}")

        if response.status_code == 200:
            _json_response = await response.json()

            is_blocked = _json_response.get("blocked", False)
            if is_blocked:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "Violated guardrail policy",
                        "zguard_response": _json_response,
                    },
                )
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail={
                    "error": f"ZGuard API request failed with status {response.status_code}",
                    "response": response.text,
                },
            )

    @log_guardrail_information
    async def async_post_call_success_hook(
        self,
        data: dict,
        user_api_key_dict: UserAPIKeyAuth,
        response,
    ):
        from litellm.proxy.common_utils.callback_utils import (
            add_guardrail_to_applied_guardrails_header,
        )

        event_type: GuardrailEventHooks = GuardrailEventHooks.post_call
        if self.should_run_guardrail(data=data, event_type=event_type) is not True:
            return

        response_str: Optional[str] = convert_litellm_response_object_to_str(response)
        if response_str is not None:
            await self.make_zguard_api_request(
                content=response_str,
                direction="OUT",
                request_data=data,
            )

            add_guardrail_to_applied_guardrails_header(
                request_data=data, guardrail_name=self.guardrail_name
            )

    @log_guardrail_information
    async def async_moderation_hook(
        self,
        data: dict,
        user_api_key_dict: UserAPIKeyAuth,
        call_type: Literal[
            "completion",
            "embeddings",
            "image_generation",
            "moderation",
            "audio_transcription",
            "responses",
            "mcp_call",
        ],
    ):
        from litellm.proxy.common_utils.callback_utils import (
            add_guardrail_to_applied_guardrails_header,
        )
        from litellm.proxy.guardrails.guardrail_helpers import (
            should_proceed_based_on_metadata,
        )

        event_type: GuardrailEventHooks = GuardrailEventHooks.during_call
        if self.should_run_guardrail(data=data, event_type=event_type) is not True:
            return

        if (
            await should_proceed_based_on_metadata(
                data=data,
                guardrail_name=GUARDRAIL_NAME,
            )
            is False
        ):
            return

        content: Optional[str] = None
        if "messages" in data and isinstance(data["messages"], list):
            content = self.extract_text_from_messages(messages=data["messages"])

        if content is not None:
            await self.make_zguard_api_request(
                content=content,
                direction="IN",
                request_data=data,
            )
            add_guardrail_to_applied_guardrails_header(
                request_data=data, guardrail_name=self.guardrail_name
            )
        else:
            verbose_proxy_logger.warning(
                "ZGuard: not running guardrail. No messages in data"
            )

    @staticmethod
    def get_config_model() -> Optional[Type["GuardrailConfigModel"]]:
        from litellm.types.proxy.guardrails.guardrail_hooks.zguard import (
            ZGuardGuardrailConfigModel,
        )

        return ZGuardGuardrailConfigModel
