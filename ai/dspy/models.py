"""Model registry & LLM provider adapter (dspy-free, read-only, offline-safe).

The DSPy layer is deliberately provider-agnostic. ``lm.py`` is the *adapter*: it
resolves the active provider + model from env-driven settings so TrederAIG can
run the same school programs against Llama 3.2 (Ollama local on ``E:\\MLL``),
Qwen / Gemma / Mistral, or a cloud provider without rebuilding the programs.
This module is the *observable half* of that contract:

  providers  -> adapters available right now (key / local-endpoint presence)
  models     -> models actually available (probed from the local Ollama server)
  configured -> what is selected right now (provider + model or auto-model)

Nothing here imports ``dspy``, and every network probe is bound to a short
timeout so status/API surfaces stay fast (and honest) offline.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict

from .lm import LM_API_KEY_ENV, LM_BASE_URL_ENV, LM_ENV, _provider

OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"

# auto-models lm.py would fall back to per provider (provider swap contract).
DEFAULT_MODELS = {
    "openai": "openai/gpt-4o",
    "anthropic": "anthropic/claude-sonnet-4-5",
    "local": LM_ENV,
}

CLOUD_KEYS = (("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"))


def probe_local_models(timeout: float = 4.0) -> Dict[str, Any]:
    """List models served by the local Ollama server (best-effort).

    Returns ``reachable: False`` (and no models) when the server is down / slow,
    never raises.
    """
    try:
        req = urllib.request.Request(
            OLLAMA_TAGS_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {"reachable": False, "models": []}
    models = []
    for m in payload.get("models", []):
        models.append({
            "name": m.get("name"),
            "size_gb": round((m.get("size") or 0) / 1024 ** 3, 2),
            "digest": (m.get("digest") or "")[:12],
        })
    return {"reachable": True, "models": models}


def catalog() -> Dict[str, Any]:
    """Full model-registry snapshot (read-only; never imports dspy)."""
    import importlib.util
    local = probe_local_models()

    dspy_ok = importlib.util.find_spec("dspy") is not None

    provider_entry = []
    base_url = os.environ.get(LM_BASE_URL_ENV, "") or ""
    provider_entry.append({
        "provider": "local",
        "kind": "openai-compatible endpoint (Ollama / LM Studio / vLLM)",
        "key_present": bool(os.environ.get(LM_API_KEY_ENV)),
        "base_url": base_url or None,
        "reachable": local["reachable"],
        "model_count": len(local["models"]),
    })
    for provider, key in CLOUD_KEYS:
        provider_entry.append({
            "provider": provider,
            "kind": "cloud",
            "key_present": bool(os.environ.get(key)),
            "base_url": None,
            "reachable": None,
            "model_count": 0,
        })

    configured = _provider()
    return {
        "ok": True,
        "dspy_installed": dspy_ok,
        "providers": provider_entry,
        "models": local["models"],
        "local_reachable": local["reachable"],
        "configured": {
            "provider": configured,
            "model": os.environ.get(LM_ENV) or None,
            "api_key_present": bool(os.environ.get(LM_API_KEY_ENV)
                                    or os.environ.get("OPENAI_API_KEY")
                                    or os.environ.get("ANTHROPIC_API_KEY")),
            "auto_model": DEFAULT_MODELS.get(configured),
        },
        "adapter": {
            "note": "switch provider by env, not by code (TRADERAIG_DSPY_LM_BASE_URL / "
                    "OPENAI_API_KEY / ANTHROPIC_API_KEY)",
            "priority": "local(base_url) > anthropic(no openai key) > openai > dspy",
        },
    }


__all__ = ["catalog", "probe_local_models", "DEFAULT_MODELS"]
