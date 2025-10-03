from typing import Optional

from pydantic import Field

from .base import GuardrailConfigModel


class ZGuardGuardrailConfigModel(GuardrailConfigModel):
    api_key: Optional[str] = Field(
        default=None,
        description="The API key (Bearer token) for the ZGuard guardrail. If not provided, the `ZGUARD_API_KEY` environment variable is checked.",
    )
    api_base: Optional[str] = Field(
        default=None,
        description="The API base URL for the ZGuard guardrail. If not provided, defaults to `https://zseclipse.net/v1/detection`.",
    )
    policy_id: Optional[int] = Field(
        default=None,
        description="The policy ID for ZGuard content detection. If not provided, the `ZGUARD_POLICY_ID` environment variable is checked.",
    )

    @staticmethod
    def ui_friendly_name() -> str:
        return "ZGuard"
