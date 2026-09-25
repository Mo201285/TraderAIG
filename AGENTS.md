# AGENTS.md — TraderAIG Institutional Operating Core

Brief for new agents/explorers. The complete engineering discipline lives in
`ENGINEERING MAST.md` (its §26 binds the universal rules to this repo); this
file is the 60-second brief that points at it.

## What this is

Institutional investment operating core: Python backend (FastAPI, :8000) over
MetaTrader 5, with a React/TypeScript dashboard (`TAIG Dash`, :8443) and one
bilingual operator console `tools/tradraig.py` (EN/AR, stdlib-only, works with or
without the API up). Windows / PowerShell 5.1.

## Sources of truth (in order)

1. Explicit user requirements
2. `PROJECT_MAP.md` — roadmap, milestone map, ORPHANS & PENDING, QUICK_COMMANDS, DECISION_LOG
3. `ENGINEERING MAST.md` — universal rules + THIS repo's annex (must-read §26)
4. `UPDATE.md` — Unified Operating Spec v1.1.0 + Appendix A (implementation status table)
5. `OPERATOR_RUNBOOK.md` — operator workflows + symptom→action table
6. `README.md` — quick start / feature map (bilingual EN/AR)
7. Existing tests → existing implementation

If any two conflict: STOP, surface the conflict, never silently pick one.

## Verification gate (before declaring anything done)

- One command: `powershell -ExecutionPolicy Bypass -File scripts\verify_all.ps1` (gates: ruff lint → py_compile → full pytest → `tsc`+`vite build` → live smoke; use `-SkipSmoke` for everything except the live boot)
- Lint: `python -m ruff check .` in `D:\One` (must be zero; config in `pyproject.toml`)
- Backend: `python -m pytest -q` in `D:\One` (baseline **619 passing** — report the new count when it moves)
- Dashboard: in `TAIG Dash` run `node .\node_modules\typescript\bin\tsc --noEmit` then `node .\node_modules\vite\bin\vite.js build` (no page is done without both)
- Live wire: `powershell -ExecutionPolicy Bypass -File scripts\smoke_live.ps1` (7/7 steps on a real uvicorn boot)

## Core conventions

- **Single authority**: anything that mutates durable decision state flows through the API; console commands call the API, they never mutate directly.
- **Engine-safety guard**: promote/quarantine applies run under the ReviewLoop guard — a running engine means HTTP 409 and the request stays pending (retryable). This contract is tested; preserve it.
- **No research→live shortcut**: DSPy/Strategy Lab produce candidates that reach production only via governed change requests.
- **Docs discipline**: completing any milestone/orphan flips `[ ]`→`[x]` in PROJECT_MAP, adds a dated DECISION_LOG row (Accepted/Rationale/Rejected), and keeps README/RUNBOOK/UPDATE-annex in sync.
- **Dashboard honesty**: no fabricated numbers; absent sources render `EmptyState`/`—` with the live/mock banner; mocks in `lib/mocks.ts`, API→UI adapters in `lib/adapters.ts`.

## Environment notes

- Win32 + PowerShell 5.1 (cp1252). For unicode console output use `python -c` with `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`.
- Stdlib-first: never add a dependency when the stdlib solves it.
- pytest tests prepend root via `sys.path.insert(0, str(Path(__file__).resolve().parents[2]))`.
- Optional externals must degrade to zero-infra defaults: Redis `TRADERAIG_STATE_REDIS=0`, persistence `TRADERAIG_PERSIST=0`, Postgres (`POSTGRES_HOST` empty → SQLite), DSPy gate `TRADERAIG_DSPY_ENABLED`.

## Blocked (external services only — do not fake/implement around)

- Real MT5 execution is PROVEN on the demo terminal via python-MT5 (`scripts/mt5_live_session.py`, live round-trips + history→ledger), and the **MQL5 EA channel is fully wired**: file bridge (`execution/bridge.py`) + **real-time WebSocket channel** (`operations/ws_bridge.py` ↔ `scripts/mt5_bridge_proxy.py`, verified 2026-09-25). What remains external is the **production trading-host attach** — pointing the channel at the company/real host is a deployment/host-choice decision, no code gap.
- Wallet/payment integration is SHIPPED **sandbox-first** (in-process ledger, zero network) with Stripe wired (real REST, live only under `PAYMENTS_MODE=live` + `PAYMENTS_LIVE_ALLOWED=1` + key) and Pi an honest not-wired stub (server SDK missing). Remaining external: **live payment provisioning** (real Stripe keys; Pi SDK), and OKX **live-funded read**/orders — the OKX read probe fully works (`scripts/cex_okx_probe.py` + `scripts/cex_okx_demo_probe.py` exit 0 on real signed `account/balance`: curl transport beats urllib's Cloudflare-1010 ban, ISO-8601 UTC ms timestamps instead of epoch, `curl -4` to match the key's IPv4 allowlist); demo key `f7e78f…` + passphrase verified. Live *orders* stay gated by `CEX_LIVE_ALLOWED=1`.
