# AGENTS.md — TraderAIG Institutional Operating Core

Brief for new agents/explorers. The complete engineering discipline lives in
`ENGINEERING MAST.md` (its §26 binds the universal rules to this repo; §27 adds the
TrederAIG Intelligence & Investment Engineering Rules, §28 the Product & Website
Engineering Rules); this file is the 60-second brief that points at it.

## What this is

Institutional investment operating core: Python backend (FastAPI, :8000) over
MetaTrader 5, with a React/TypeScript dashboard (`TAIG Dash`, :8443) and one
bilingual operator console `tools/tradraig.py` (EN/AR, stdlib-only, works with or
without the API up). Windows / PowerShell 5.1.

## Sources of truth (in order)

1. Explicit user requirements
2. `PROJECT_MAP.md` — roadmap, milestone map, ORPHANS & PENDING, QUICK_COMMANDS, DECISION_LOG
3. `ENGINEERING MAST.md` — universal rules + THIS repo's annex (must-read §26, §27 TrederAIG Intelligence & Investment Engineering Rules, §28 Product & Website Engineering Rules; §3.1 Investment Source-of-Truth Hierarchy)
4. `UPDATE.md` — Unified Operating Spec v1.1.0 + Appendix A (implementation status table)
5. `OPERATOR_RUNBOOK.md` — operator workflows + symptom→action table
6. `README.md` — quick start / feature map (bilingual EN/AR)
7. Existing tests → existing implementation

If any two conflict: STOP, surface the conflict, never silently pick one.

## Verification gate (before declaring anything done)

- One command: `powershell -ExecutionPolicy Bypass -File scripts\verify_all.ps1` (gates: ruff lint → py_compile → full pytest → `tsc`+`vite build` → live smoke; use `-SkipSmoke` for everything except the live boot)
- Lint: `python -m ruff check .` in `D:\One` (must be zero; config in `pyproject.toml`)
- Backend: `python -m pytest -q` in `D:\One` (baseline **1152 of 1153 collected passing** as of row 739; report the new count when it moves. The one exception is `tests/test_operations/test_system_health.py::test_market_data_health_is_healthy_only_with_a_fresh_feed`, which fails only under load — it passes in isolation in ~10s and on rerun, so treat it as a **known flake, not a green test**: report it if it fails, do not re-run until it goes green and call the suite clean. Also note this count was measured with an uncommitted parallel workstream in the tree, so it includes tests that are not yet committed)
- Dashboard: in `TAIG Dash` run `node .\node_modules\typescript\bin\tsc --noEmit` then `node .\node_modules\vite\bin\vite.js build` (no page is done without both)
- Live wire: `powershell -ExecutionPolicy Bypass -File scripts\smoke_live.ps1` (7/7 steps on a real uvicorn boot)

## Core conventions

- **Single authority**: anything that mutates durable decision state flows through the API; console commands call the API, they never mutate directly.
- **Engine-safety guard**: promote/quarantine applies run under the ReviewLoop guard — a running engine means HTTP 409 and the request stays pending (retryable). This contract is tested; preserve it.
- **No research→live shortcut**: DSPy/Strategy Lab produce candidates that reach production only via governed change requests.
- **Governance is the final operational authority**: approval/rejection/risk limits/promotion/quarantine/production activation all route through Governance OS. AI/LLMs/DSPy are reasoning components — they may interpret/propose/generate, never place live trades, promote, or modify production risk without governed approval (§27). The user interface is a surface of the Control Plane, never a second authority and never the source of truth (§28).
- **User strategy lifecycle**: a natural-language description is captured verbatim → canonical Strategy Specification → ambiguity detection → user confirmation → vetting → research → validation → paper → governance → production; failure yields explicit REJECTED/QUARANTINED/NEEDS_REVISION, never silent deletion (§27.3–27.4, §28.5–28.8).
- **Docs discipline**: completing any milestone/orphan flips `[ ]`→`[x]` in PROJECT_MAP, adds a dated DECISION_LOG row (Accepted/Rationale/Rejected), and keeps README/RUNBOOK/UPDATE-annex in sync.
- **Dashboard honesty**: no fabricated numbers; absent sources render `EmptyState`/`—` with the live/mock banner; mocks in `lib/mocks.ts`, API→UI adapters in `lib/adapters.ts`.
- **One process, one canonical state**: an engine runs *inside* the API process (`/mt5/watcher`, `/paper/engine/start`, `/cex/engine/start`), never as its own scheduled process. A second process owns a second `MarketPlane`, a second `core.state` and a second opportunity board, and the failure is silent rather than loud. `scripts/paper_engine.py` was deleted for exactly this reason — do not bring it back.
- **Documented ≠ implemented**: `New Expind dev.md` and the [TECH_STACK] table describe RabbitMQ; there is no `pika`/`amqp` dependency or code path, and the runtime database is SQLite unless `POSTGRES_HOST` is set. Verify a claim against the running system before repeating it (§28.4).

## Environment notes

- Win32 + PowerShell 5.1 (cp1252). For unicode console output use `python -c` with `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`.
- Stdlib-first: never add a dependency when the stdlib solves it.
- pytest tests prepend root via `sys.path.insert(0, str(Path(__file__).resolve().parents[2]))`.
- Optional externals must degrade to zero-infra defaults: Redis `TRADERAIG_STATE_REDIS=0`, persistence `TRADERAIG_PERSIST=0`, Postgres (`POSTGRES_HOST` empty → SQLite), DSPy gate `TRADERAIG_DSPY_ENABLED`.
- 24/7 services on this host: `scripts/mt5_host_watchdog.py` (terminal, report-only), `scripts/ensure_backend.py` (backend + tier-100 rail + paper desk), `scripts/ensure_dashboard.py` (verified `dist/` on :8443 via `vite preview`). Each resolves its root from `__file__` and `.resolve()` — a relative root makes every log path depend on the scheduled task's working directory. Scheduled tasks: `TAIG-Backend-Start`, `TAIG-Backend-Watchdog`, `TAIG-MT5-Terminal-Start`, `TAIG-MT5-Watchdog`, `TAIG-Dashboard-Watchdog`.

## Blocked (external services only — do not fake/implement around)

- Real MT5 execution is PROVEN on the demo terminal via python-MT5 (`scripts/mt5_live_session.py`, live round-trips + history→ledger), and the **MQL5 EA channel is fully wired**: file bridge (`execution/bridge.py`) + **real-time WebSocket channel** (`operations/ws_bridge.py` ↔ `scripts/mt5_bridge_proxy.py`, verified 2026-09-25). What remains external is the **production trading-host attach** — pointing the channel at the company/real host is a deployment/host-choice decision, no code gap.
- Wallet/payment integration is SHIPPED **sandbox-first** (in-process ledger, zero network) with Stripe wired (real REST, live only under `PAYMENTS_MODE=live` + `PAYMENTS_LIVE_ALLOWED=1` + key) and Pi an honest not-wired stub (server SDK missing). Remaining external: **live payment provisioning** (real Stripe keys; Pi SDK), and OKX **live-funded read**/orders — the OKX read probe fully works (`scripts/cex_okx_probe.py` + `scripts/cex_okx_demo_probe.py` exit 0 on real signed `account/balance`: curl transport beats urllib's Cloudflare-1010 ban, ISO-8601 UTC ms timestamps instead of epoch, `curl -4` to match the key's IPv4 allowlist); demo key `f7e78f…` + passphrase verified. Live *orders* stay gated by `CEX_LIVE_ALLOWED=1`.
