from typing import TYPE_CHECKING

from litellm.types.guardrails import SupportedGuardrailIntegrations

from .zguard import ZGuardGuardrail

if TYPE_CHECKING:
    from litellm.types.guardrails import Guardrail, LitellmParams


def initialize_guardrail(litellm_params: "LitellmParams", guardrail: "Guardrail"):
    import litellm

    policy_id = None
    if hasattr(litellm_params, "policy_id"):
        policy_id = litellm_params.policy_id
    elif isinstance(litellm_params, dict):
        policy_id = litellm_params.get("policy_id")

    _zguard_callback = ZGuardGuardrail(
        api_base=litellm_params.api_base,
        api_key=litellm_params.api_key,
        policy_id=policy_id,
        guardrail_name=guardrail.get("guardrail_name", ""),
        event_hook=litellm_params.mode,
        default_on=litellm_params.default_on,
    )
    litellm.logging_callback_manager.add_litellm_callback(_zguard_callback)

    return _zguard_callback


guardrail_initializer_registry = {
    SupportedGuardrailIntegrations.ZGUARD.value: initialize_guardrail,
}


guardrail_class_registry = {
    SupportedGuardrailIntegrations.ZGUARD.value: ZGuardGuardrail,
}
