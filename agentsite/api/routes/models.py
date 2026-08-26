"""Model discovery endpoint."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from agentsite.config import settings

logger = logging.getLogger("agentsite.api.models")
router = APIRouter(prefix="/api/models", tags=["models"])

ENV_PATH = Path.cwd() / ".env"


@router.get("")
async def list_models():
    """Auto-detect available models from configured providers with capabilities."""
    try:
        from prompture import get_available_models

        enriched = get_available_models(include_capabilities=True)
    except Exception as exc:
        logger.warning("Model discovery failed: %s", exc)
        enriched = []

    # Try to import pricing helper
    try:
        from prompture.infra import get_model_rates
    except ImportError:
        get_model_rates = None

    # Group by provider
    groups: dict[str, list[dict]] = {}
    for entry in enriched:
        provider = entry.get("provider", "unknown")
        raw_id = entry["model_id"]
        # Always prefix with the provider so the pipeline knows which
        # service to route to (e.g. openrouter/moonshotai/kimi-k2.5).
        model_id = f"{provider}/{raw_id}" if not raw_id.startswith(f"{provider}/") else raw_id
        caps = entry.get("capabilities") or {}

        # Fetch pricing from models.dev cache (per 1M tokens)
        pricing = None
        if get_model_rates is not None:
            try:
                rates = get_model_rates(provider, raw_id)
                if rates:
                    pricing = {
                        "input": rates.get("input"),
                        "output": rates.get("output"),
                    }
            except Exception:
                pass

        groups.setdefault(provider, []).append(
            {
                "id": model_id,
                "provider": provider,
                "context_window": caps.get("context_window"),
                "max_output_tokens": caps.get("max_output_tokens"),
                "supports_tool_use": caps.get("supports_tool_use", False),
                "supports_vision": caps.get("supports_vision", False),
                "supports_structured_output": caps.get(
                    "supports_structured_output", False
                ),
                "is_reasoning": caps.get("is_reasoning", False),
                "pricing": pricing,
            }
        )

    # Sort models within each group
    for provider in groups:
        groups[provider].sort(key=lambda m: m["id"])

    return {"groups": groups}


@router.get("/default")
async def get_default_model():
    """Return the current default model."""
    return {"model": settings.default_model}


class DefaultModelUpdate(BaseModel):
    model: str


@router.put("/default")
async def set_default_model(body: DefaultModelUpdate):
    """Set the default model in .env and reload settings."""
    key = "AGENTSITE_DEFAULT_MODEL"
    value = body.model

    # Update .env file
    content = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    pattern = re.compile(rf"^#?\s*{re.escape(key)}\s*=.*$", re.MULTILINE)
    replacement = f"{key}={value}"

    if pattern.search(content):
        content = pattern.sub(replacement, content, count=1)
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        content += f"{replacement}\n"

    ENV_PATH.write_text(content, encoding="utf-8")
    os.environ[key] = value

    # Reload settings so settings.default_model reflects the change
    settings.default_model = value

    return {"ok": True, "model": value}
