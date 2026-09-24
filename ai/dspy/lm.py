"""LLM provider wiring (dspy-free spec + lazy configure).

How the layer connects to a provider:

  provider       env                                                   auto model
  --------------- ----------------------------------------------------- -----------------
  OpenAI          TRADERAIG_DSPY_ENABLED=1 + OPENAI_API_KEY=sk-...      gpt-4o (dspy default)
  Anthropic       TRADERAIG_DSPY_ENABLED=1 + ANTHROPIC_API_KEY=sk-...   dspy default
  Local (Ollama/  TRADERAIG_DSPY_ENABLED=1 + TRADERAIG_DSPY_LM=model +  model you choose
  LM Studio /     TRADERAIG_DSPY_LM_BASE_URL=http://127.0.0.1:11434/v1
  vLLM)           (OpenAI-compatible; ONNXRuntime local requires model)

``lm_spec()`` only touches the environment (safe offline and from the status
endpoint). ``configure_lm()`` imports dspy and calls ``dspy.configure(lm=...)``
— it must run *inside the worker subprocess*, never in the API.
"""

from __future__ import annotations

import os
from typing import Any, Dict

LM_ENV = "TRADERAIG_DSPY_LM"
LM_BASE_URL_ENV = "TRADERAIG_DSPY_LM_BASE_URL"
LM_API_KEY_ENV = "TRADERAIG_DSPY_LM_API_KEY"

VALID_PROVIDERS = ("openai", "anthropic", "local", "dspy")


def _provider() -> str:
    if os.environ.get(LM_BASE_URL_ENV):
        return "local"
    if os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY") or os.environ.get(LM_API_KEY_ENV):
        return "openai"
    return "dspy"


def lm_spec() -> Dict[str, Any]:
    """Read provider configuration from the environment (never imports dspy)."""
    model = os.environ.get(LM_ENV, "") or ""
    base_url = os.environ.get(LM_BASE_URL_ENV, "") or ""
    api_key = (os.environ.get(LM_API_KEY_ENV)
               or os.environ.get("OPENAI_API_KEY")
               or os.environ.get("ANTHROPIC_API_KEY") or "")
    provider = _provider()

    error = ""
    if provider == "local" and not model:
        error = (f"{LM_BASE_URL_ENV} requires {LM_ENV}=<model id> "
                 "(e.g. llama3.1:8b for Ollama); got none")
    if provider in ("openai", "anthropic", "local") and not api_key:
        # some local servers accept an empty/dummy key; still require the env
        # so the gate is uniform.
        error = error or "no API key configured for provider"
    if not error and provider == "dspy":
        error = "no provider configured (set OPENAI_API_KEY / ANTHROPIC_API_KEY / " \
                f"{LM_BASE_URL_ENV})"

    return {
        "ok": error == "",
        "provider": provider,
        "model": model or None,
        "base_url": base_url or None,
        "api_key_present": bool(api_key),
        "error": error,
    }


def configure_lm(verbose: bool = False) -> Dict[str, Any]:
    """Configure dspy's LM from the environment (lazy; imports dspy)."""
    spec = lm_spec()
    if not spec["ok"]:
        return spec

    import dspy

    provider = spec["provider"]
    try:
        if provider == "local":
            # litellm needs the provider prefix even for an OpenAI-compatible
            # local endpoint (api_base supplies the routing host).
            lm = dspy.LM(
                model=f"openai/{spec['model']}",
                api_base=spec["base_url"],
                api_key=os.environ.get(LM_API_KEY_ENV) or "not-needed",
            )
        elif provider == "anthropic":
            lm = dspy.LM(model="anthropic/claude-sonnet-4-5",
                         api_key=os.environ["ANTHROPIC_API_KEY"])
        else:  # openai (auto)
            lm = dspy.LM(model=spec["model"] or "openai/gpt-4o",
                         api_key=spec["api_key_present"] and
                         (os.environ.get(LM_API_KEY_ENV) or os.environ.get("OPENAI_API_KEY")))
        dspy.configure(lm=lm)
    except Exception as exc:
        return {"ok": False, "provider": provider,
                "error": f"{type(exc).__name__}: {exc}"}
    return {**spec, "configured": True, "lm_ref": lm,
            "model": spec["model"] or ("openai/gpt-4o" if provider == "openai"
                                       else "anthropic/claude-sonnet-4-5")}


__all__ = ["LM_ENV", "LM_BASE_URL_ENV", "LM_API_KEY_ENV", "lm_spec", "configure_lm"]
