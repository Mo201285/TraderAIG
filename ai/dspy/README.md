# ai/dspy — DSPy AI Program Evolution Layer

**Standalone, contract-first, research-only.** DSPy (Stanford) improves *how
each school reasons and selects evidence*; it never opens, sizes, vetoes or
routes a trade. This package is the organized analysis/learning/optimization
layer requested for the project — not random prompt experiments scattered
through the codebase.

## Philosophy (order matters)

```
Market Data → Deterministic Engine → structured market state (NO raw OHLC)
           → School Programs (DSPy) → SchoolEvidence verdict
           → Fusion → Decision/Risk/Governance → Backtest → Outcome
           → Evaluation (professional trading metric)  ← must exist FIRST
           → DSPy Optimization → promotion registry → next version
```

- **Signatures first** (contracts), then **Modules**, then **Programs**.
- Program inputs are always **structured state** (symbol, timeframe, trend,
  external high/low, liquidity, sweep, displacement, FVG, session, ATR …), not candles.
- Output follows the **SchoolEvidence standard**: `direction, setup,
  confidence, evidence[], invalidation[], created_at`.
- Optimisation runs only after a reliable evaluation metric exists.

## Layout

```
ai/dspy/
  signatures/   contracts.py   5 program signature specs + lazy make_signatures()
  modules/      market.py      MarketAnalyzer (per-school module) + lazy build_module()
  programs/     ict.py         ICTProgram (module chain) + catalogue (ict_scalping)
  optimizers/   registry.py    GEPA → MIPROv2 → BootstrapFewShot, version-safe
                run.py         optimize_program(): corpus → examples → baseline
                               scoring → optimiser compile (evaluation first),
                               gated so dspy is only imported when it must run
  evaluators/   metrics.py     professional trading metric (decision/entry/risk/
                               timing, MAE/MFE, R:R, regime, drawdown impact,
                               false-positive penalty) — pure Python, dspy-free
                evaluation.py  evaluate_program(): score any callable
  datasets/     strategy_lab.py read-only adapter over research/strategy_lab
                               observations (xauusd/btcusd corpus)
  registry/     programs.py    AIProgramVersion + JSON promotion registry
                               (research → candidate → validated → paper →
                               production / quarantined)
  models.py                    LLM adapter / model registry snapshot (read-only:
                               providers, local Ollama models probed, which is
                               configured + the swap contract)
  runtime.py                   lazy/gated availability probe (find_spec +
                               importlib.metadata; never imports dspy)
  harness.py                   watchdogged subprocess runner (hard timeout)
  worker.py                    the ONLY place dspy may be imported (child proc)
  compiler.py                  AIProgramCompiler facade (optimize/reflect/evaluate)
  connect.py                   opt-in hooks into core/pipeline.py + backtest
```

## Offline safety

`import dspy` can block without network (verified on this machine), so the
whole package is **lazy + gated**:

- Env gate: `TRADERAIG_DSPY_ENABLED=1` **and** an LLM provider key
  (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `DSPY_LM_API_KEY`).
- No in-process dspy import anywhere. DSPy work runs in a **watchdogged
  subprocess** with a hard timeout → a stalled provider yields a controlled
  `{ok: false, reason: "dspy harness timed out after Ns ..."}`.
- `evaluators/`, `registry/`, `datasets/`, `connect.py` logic is pure Python
  and works everywhere.

## Usage

```python
from ai.dspy.runtime import status
status()                       # {'enabled': False, 'dspy_version': '3.3.1', ...}

from ai.dspy.compiler import AIProgramCompiler
AIProgramCompiler("ict_scalping").evaluate(limit=20)   # metric-bound, offline OK
AIProgramCompiler("ict_scalping").optimize(trials=6)   # harness; gate-off → controlled false

# deterministic offline verdict (no dspy at all):
from ai.dspy.programs import ICTProgram
ICTProgram().run({"symbol": "XAUUSD", "timeframe": "M15", "bias": "bullish", ...})
```

Live surface: `GET /research/dspy/status` (non-blocking).

## Connecting an LLM provider

Three ways; the worker reads these env vars (see `ai/dspy/lm.py`). Status
shows the resolved provider via `{"lm": {...}}` — run `/research/dspy/status`
after setting them.

**1) OpenAI (cloud)**
```powershell
$env:TRADERAIG_DSPY_ENABLED="1"
$env:OPENAI_API_KEY="sk-..."
```
(optional) `$env:TRADERAIG_DSPY_LM="openai/gpt-4o"`

**2) Anthropic (cloud)**
```powershell
$env:TRADERAIG_DSPY_ENABLED="1"
$env:ANTHROPIC_API_KEY="sk-ant-..."
```
Do **not** set `OPENAI_API_KEY` at the same time (provider detection prefers it).

**3) Local (Ollama / LM Studio / vLLM) — recommended for this 6 GB RAM box**
```powershell
$env:TRADERAIG_DSPY_ENABLED="1"
$env:TRADERAIG_DSPY_LM_BASE_URL="http://127.0.0.1:11434/v1"   # Ollama OpenAI-compatible endpoint
$env:TRADERAIG_DSPY_LM="llama3.1:8b"                           # a real model id
$env:TRADERAIG_DSPY_LM_API_KEY="ollama"                        # local: any value
```
Run one first: `ollama pull llama3.1:8b` (small → fits the 6 GB budget; DSPy
BootstrapFewShot is the cheapest optimiser for it).

> **Status on this machine (2026-09-22):** a local provider is already running,
> entirely on `E:` — `E:\MLL\Ollama\ollama.exe serve` (models in
> `E:\MLL\models`: `qwen2.5:7b` stored but not runnable on 6 GB, `llama3.2:3b` +
> `llama3.2:1b` runnable), plus `E:\MLL\Bionic`; env vars
> are set at **User** scope:
> `TRADERAIG_DSPY_LM_BASE_URL=http://127.0.0.1:11434/v1`,
> `TRADERAIG_DSPY_LM=llama3.2:1b`, `TRADERAIG_DSPY_LM_API_KEY=ollama`.
> `/research/dspy/status` returns `"lm": {"provider": "local", "model": "llama3.2:1b", ...}`
> and `/research/dspy/models` lists the adapters + local catalogue.
> Real compiles are proven (BootstrapFewShot, candidates `ict_scalping-v13..v18`).
> The layer gate (`TRADERAIG_DSPY_ENABLED`) still defaults to **off** — turn it
> on explicitly in the environment where you want optimization to run. Note
> `import dspy` here takes ~28s and the watchdog must not be too tight.

Then trigger an optimisation work and watch the watchdog report:
```powershell
python -m ai.dspy.worker optimize --programs ict_scalping --trials 6 --sleep 0
```
If the provider is unreachable you get a controlled `timed out` report — the
API/loop is never frozen. Any success is stamped as a **candidate** version in
`ai/dspy/registry/data/programs.json`, carrying real compilation provenance
(optimizer, baseline/compiled score, LM provider/model, serialization, trials).

Observation surfaces (read-only, safe offline):
- `GET /research/dspy/status` — gating, provider config, corpus, governance.
- `GET /research/dspy/models` — the LLM **adapter + model registry**: adapters
  available right now (local endpoint reachable + models probed, cloud keys),
  what is configured, and the swap contract.
- `GET /research/dspy/registry` — the candidate promotion ladder with provenance.
- `AIProgramCompiler().evidence()` — read-only evidence change proposal for the
  validation lab (what the current candidate would propose, no trades touched).
- `ai/dspy/intake.py` — `candidate_dossier()` / `save_proposal()`: a dossier per
  candidate persisted under `registry/data/proposals/` (read-only for the lab).

## Model registry / provider adapter (Llama is not hard-wired)

DSPy is the **AI-program runtime + optimization layer**; the LLM (Llama 3.2
locally, or Qwen / Gemma / Mistral / a cloud model) is only the *reasoner* the
compiled programs call. Schools, signatures and evaluators are written once and
providers are swapped through **environment, not code**:

- `TRADERAIG_DSPY_LM_BASE_URL` → `local` (Ollama / LM Studio / vLLM | auto model:
  value of `TRADERAIG_DSPY_LM`).
- `OPENAI_API_KEY` (+ optional `TRADERAIG_DSPY_LM`) → `openai`.
- `ANTHROPIC_API_KEY` → `anthropic`.
- Priority: `local (base_url) > anthropic (only when no openai key) > openai > dspy`.

`ai/dspy/models.py` publishes this contract read-only; `/research/dspy/models`
shows exactly that: adapter list, availability, and the currently selected
provider/model. Output stays the **SchoolEvidence standard**, so replacing the
model never changes TrederAIG's decision/governance chain.

**Measured local portfolio on this 6 GB box (2026-09-22):**

| model | size on E: | runs here? | measured |
| ----- | ---------- | ---------- | -------- |
| llama3.2:1b | 1.23 GB | ✅ | compiles + serializes demos (v18) |
| llama3.2:3b | 2.00 GB | ✅ | practical ceiling (full compile ~19 min) |
| qwen2.5:7b | 4.70 GB | ❌ | Q4 4.4 GB > ~3 GB free RAM → swap-storm, 0 tok/s |

Swapping providers/models is **env-only** (`TRADERAIG_DSPY_LM=qwen2.5:7b`, or
`OPENAI_API_KEY` for cloud). The 7b is stored on E: and adapter-ready: it needs
≥16 GB RAM or a GPU (or a remote endpoint) — no code change then.

**Market State contract:** like the deterministic market engines, LLM inputs are
always *structured state* (session, regime, liquidity, FVG, displacement,
evidences …), never raw OHLC — the school programs consume the SAME signed
fields the deterministic engines produce. Llama never recomputes BOS/FVG/ATR.

**Serialization honesty:** `program_serialized` is only `true` when a compiled
program's state actually persists (>200 chars of JSON). Until the 2026-09-22
module fix, `build_module` held the predictor in a closure, so
`named_predictors()` was empty, DSPy silently dropped every bootstrapped demo
(`predictor2name[id] → KeyError → continue`) and the compiled program equalled
the untrained baseline. With the predictor now an instance attribute, candidate
`ict_scalping-v18` (`llama3.2:1b`) carries **real demos**: `program_serialized:
true`, artifact `registry/data/programs/ict_scalping-v18.json` (2.6 KB);
compiled_score 0.4 vs baseline 0.384. The remaining gap is label/quality: the
corpus gold fields are sparse, so few-shot gains are small until a stronger
local LM or a tradeable-adapter metric upgrades the signal.

### Opt-in pipeline / backtest hooks (off by default)

```bash
export TRADERAIG_DSPY_ENABLED=1      # on a networked env with an LLM key
export TRADERAIG_DSPY_PIPELINE=1     # refine pipeline evidence + backtest recap
```

- `core/pipeline.py` → `TradingLoop._maybe_dspy_refine(evidence)` (no-op unless opted in).
- `operations/backtest.py` → `post_run_dspy_report(report)` (metric recap; None otherwise).

## Tests

```bash
python -m pytest tests/test_ai_dspy      # 41 targeted tests, never imports dspy
```

## Governance

Every optimised outcome is a **candidate version**; promotion follows the
Strategy Lab ladder via `ai/dspy/registry/programs.py`. Nothing in this layer
touches the execution path.