"""Provider dispatch gateway for LLM requests."""

from __future__ import annotations

from time import perf_counter

from llm_core.contracts import LLMProvider, LLMRequest, LLMResponse
from llm_core.policy import TextOnlyPolicyGuard
from llm_core.router import LLMRouter
from logger import calendar_logger


class LLMGateway:
    """Executes requests through resolved provider and enriches response trace."""

    def __init__(self, router: LLMRouter, providers: dict[str, LLMProvider]):
        self.router = router
        self.providers = providers
        self.policy_guard = TextOnlyPolicyGuard()

    def generate(self, request: LLMRequest) -> LLMResponse:
        policy_decision = self.policy_guard.evaluate(
            request=request,
            allowed_mcp_servers=self.router.get_allowed_mcp_servers(),
        )
        calendar_logger.log_policy_decision(
            policy_code=policy_decision.code,
            allowed=policy_decision.allowed,
            reason=policy_decision.reason,
            details=policy_decision.details,
        )
        if not policy_decision.allowed:
            raise ValueError(f"Policy denied request: {policy_decision.code}")

        route = self.router.resolve(request)
        provider = self.providers.get(route.provider)
        if provider is None:
            raise ValueError(
                f"Provider '{route.provider}' is not registered in gateway providers map."
            )

        started_at = perf_counter()
        resolved_provider = route.provider
        resolved_model = route.model_id
        route_reason = route.reason
        try:
            response = provider.generate(request=request, model_id=route.model_id)
        except Exception as primary_error:
            standby_provider_name = self.router.get_standby_provider()
            if standby_provider_name and standby_provider_name != route.provider:
                standby_provider = self.providers.get(standby_provider_name)
                if standby_provider is not None:
                    resolved_provider = standby_provider_name
                    resolved_model = self.router.select_model_id(standby_provider_name, request.task_type)
                    route_reason = "runtime_error_fallback_to_standby"
                    calendar_logger.log_fallback(
                        from_provider=route.provider,
                        to_provider=standby_provider_name,
                        reason=f"primary_error:{type(primary_error).__name__}",
                    )
                    response = standby_provider.generate(
                        request=request,
                        model_id=resolved_model,
                    )
                else:
                    raise
            else:
                raise

        elapsed_ms = round((perf_counter() - started_at) * 1000, 2)

        response.provider = resolved_provider
        if not response.model_id:
            response.model_id = resolved_model
        response.usage = {**response.usage, "latency_ms": elapsed_ms}
        response.trace = {
            **response.trace,
            "route_reason": route_reason,
            "task_type": request.task_type,
            "text_only": request.text_only,
            "allow_mcp_tools": request.allow_mcp_tools,
        }
        calendar_logger.log_provider_selection(
            provider=response.provider,
            model=response.model_id,
            route_reason=route_reason,
            task_type=request.task_type,
        )
        calendar_logger.log_usage(usage=response.usage, trace=response.trace)
        return response
