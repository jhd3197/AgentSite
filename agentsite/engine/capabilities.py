"""Model capability detection for smart agent selection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger("agentsite.capabilities")


@dataclass
class ModelCapabilities:
    """Capabilities of a specific model."""

    supports_tools: bool = True
    supports_structured_output: bool = True
    supports_vision: bool = False
    is_reasoning: bool = False
    context_window: int | None = None
    max_output_tokens: int | None = None


def _parse_model_string(model: str) -> tuple[str, str]:
    """Parse 'provider/model' string into (provider, model_name)."""
    if "/" not in model:
        return "", model
    parts = model.split("/", 1)
    return parts[0], parts[1]


@lru_cache(maxsize=128)
def get_capabilities(model: str) -> ModelCapabilities:
    """Get capabilities for a model, with caching.

    Uses Prompture's get_model_capabilities when available, falls back
    to sensible defaults based on known provider patterns.

    Args:
        model: Model string in 'provider/model' format.

    Returns:
        ModelCapabilities with detected or default values.
    """
    provider, model_name = _parse_model_string(model)
    inferred = _infer_capabilities(provider, model_name)

    # Prompture's capabilities KB first; pattern inference fills the gaps
    # (KB fields are None when models.dev doesn't report them).
    try:
        from prompture.infra.model_rates import get_model_capabilities

        caps = get_model_capabilities(provider, model_name)
        if caps:
            return ModelCapabilities(
                supports_tools=(
                    caps.supports_tool_use
                    if caps.supports_tool_use is not None
                    else inferred.supports_tools
                ),
                supports_structured_output=(
                    caps.supports_structured_output
                    if caps.supports_structured_output is not None
                    else inferred.supports_structured_output
                ),
                supports_vision=(
                    caps.supports_vision
                    if caps.supports_vision is not None
                    else inferred.supports_vision
                ),
                is_reasoning=(
                    caps.is_reasoning if caps.is_reasoning is not None else inferred.is_reasoning
                ),
                context_window=caps.context_window,
                max_output_tokens=caps.max_output_tokens,
            )
    except ImportError:
        logger.debug("prompture.infra.model_rates.get_model_capabilities not available")
    except Exception as e:
        logger.debug("Failed to get capabilities from Prompture: %s", e)

    return inferred


def _infer_capabilities(provider: str, model_name: str) -> ModelCapabilities:
    """Infer capabilities from known provider/model patterns."""
    model_lower = model_name.lower()

    # Reasoning models (often have limited tool/structured output support)
    reasoning_patterns = ("o1", "o3", "deepseek-r1", "qwq", "reasoner")
    is_reasoning = any(p in model_lower for p in reasoning_patterns)

    # Models known to lack tool support
    no_tools_patterns = ("o1-preview", "o1-mini", "deepseek-r1")
    lacks_tools = any(p in model_lower for p in no_tools_patterns)

    # Models known to lack structured output
    no_structured_patterns = ("o1-preview", "o1-mini")
    lacks_structured = any(p in model_lower for p in no_structured_patterns)

    # Vision models (all Claude 3+ family models accept images)
    vision_patterns = (
        "vision", "4o", "gpt-4-turbo", "gemini",
        "claude-3", "claude-sonnet", "claude-opus", "claude-haiku",
    )
    has_vision = any(p in model_lower for p in vision_patterns)

    # Provider-specific defaults
    if provider == "ollama":
        # Ollama models vary widely; assume basic support
        return ModelCapabilities(
            supports_tools=False,  # Most Ollama models don't support tools well
            supports_structured_output=False,
            supports_vision="vision" in model_lower or "llava" in model_lower,
            is_reasoning=is_reasoning,
        )

    if provider == "groq":
        # Groq has good tool support for most models
        return ModelCapabilities(
            supports_tools=True,
            supports_structured_output=True,
            supports_vision=False,
            is_reasoning=is_reasoning,
        )

    # Default: assume full support for major providers
    return ModelCapabilities(
        supports_tools=not lacks_tools,
        supports_structured_output=not lacks_structured,
        supports_vision=has_vision,
        is_reasoning=is_reasoning,
    )


def supports_tools(model: str) -> bool:
    """Check if model supports tool/function calling."""
    return get_capabilities(model).supports_tools


def supports_vision(model: str) -> bool:
    """Check if model supports image inputs."""
    return get_capabilities(model).supports_vision


def supports_structured_output(model: str) -> bool:
    """Check if model supports structured output (JSON schema)."""
    return get_capabilities(model).supports_structured_output


def is_reasoning_model(model: str) -> bool:
    """Check if model is a reasoning/thinking model."""
    return get_capabilities(model).is_reasoning
