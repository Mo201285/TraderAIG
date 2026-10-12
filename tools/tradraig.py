"""TraderAIG operator console - one command for the whole system.

Professional, bilingual (EN/AR), dependency-free dev/ops surface:

    python tools/traderaig.py status                 # one-shot layer health
    python tools/traderaig.py doctor                 # self-diagnosis + fixes
    python tools/traderaig.py start  all             # API + dashboard + Ollama
    python tools/traderaig.py stop   backend         # stop one layer by port
    python tools/traderaig.py test   --fast          # targeted pytest
    python tools/traderaig.py dspy   status          # live DSPy status
    python tools/traderaig.py dspy   optimize --model llama3.2:1b --trials 2
    python tools/traderaig.py info                   # versions / models / RAM
    python tools/traderaig.py status --json          # machine-readable

Design rules:
  * stdlib only (a console must run anywhere, even before pip installs).
  * all probes are short-timeout and fail soft (a broken layer is INFO, never
    a crash).
  * env is read as process env first, then the Windows User registry
    (TRADERAIG_DSPY_* are persisted User-scope on this machine), so the console
    sees reality even from a fresh terminal.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.metadata
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
DASH_DIR = os.path.join(ROOT, "TAIG Dash")
LOG_DIR = os.path.join(ROOT, "logs")
OLLAMA_EXE = r"E:\MLL\Ollama\ollama.exe"
OLLAMA_MODELS_DIR = r"E:\MLL\models"

API_PORT = int(os.environ.get("API_PORT", "8000"))
DASH_PORT = 8443
OLLAMA_PORT = 11434

GATE_ENV = "TRADERAIG_DSPY_ENABLED"
LM_ENVS = ("TRADERAIG_DSPY_LM", "TRADERAIG_DSPY_LM_BASE_URL",
           "TRADERAIG_DSPY_LM_API_KEY", "TRADERAIG_DSPY_LM_MODEL")

# (i18n_key, live path) — the read-only feeds every dashboard widget/page uses.
BOARD_FEEDS = (
    ("f_regime", "/regime/state"),
    ("f_theses", "/strategies"),
    ("f_queue", "/strategies"),
    ("f_risk", "/risk/vetoes"),
    ("f_paper", "/paper/requests"),
    ("f_health", "/system/health"),
    ("f_validation", "/validation/reports"),
    ("f_observations", "/observations"),
    ("f_learning", "/learning/experiences"),
    ("f_audit", "/audit?limit=100"),
    ("f_plan", "/users/current/plan"),
    ("f_riskstate", "/risk/state"),
    ("f_recommendations", "/recommendations"),
    ("f_chart_tf", "/chart/timeframes"),
    ("f_chart_ctx", "/chart/context?symbol=XAUUSD&timeframe=M5&bars=60"),
)

_ANSI = {"ok": "\033[32m", "warn": "\033[33m", "bad": "\033[31m",
         "dim": "\033[2m", "bold": "\033[1m", "off": "\033[0m"}

I18N = {
    "en": {
        "layer": "LAYER", "state": "STATE", "detail": "DETAIL",
        "healthy": "Healthy", "degraded": "Degraded", "disconnected": "Disconnected",
        "error": "Error", "up": "UP",
        "api": "API (governance core)", "dash": "Dashboard (TAIG Dash)",
        "ai": "AI/DSPy gate", "ollama": "Ollama (local LLM)", "storage": "Storage",
        "corpus": "Corpus", "registry": "DSPy registry", "checks": "checks",
        "pass": "PASS", "warn_label": "WARN", "fail": "FAIL", "hint": "fix:",
        "gate_on": "DSPy gate ENABLED (persisted at User scope)",
        "gate_off": "DSPy gate disabled (persisted at User scope)",
        "gate_note": "running backend keeps its own env until restarted",
        "proposal_ok": "proposal refreshed", "proposal_missing": "no compiled candidate available",
        "board": "Command Center feeds",
        "f_regime": "Market Regime", "f_theses": "Theses", "f_queue": "Promotion Queue",
        "f_risk": "Risk Warnings", "f_paper": "Paper Execution", "f_health": "System Health",
        "f_validation": "Validation Reports", "f_observations": "Observations",
        "f_learning": "Learning Ledger", "f_audit": "Audit",
        "f_plan": "Subscriber Plan", "f_riskstate": "Risk State",
        "f_recommendations": "Recommendations", "f_chart_tf": "Chart Timeframes",
        "f_chart_ctx": "Chart Context",
        "live": "live", "empty": "empty", "static": "static", "missing": "missing",
        "down": "down", "board_note": "expected static (no live engine queue)",
        "u_created": "identity created", "u_create_offline": "API down — identities require the backend (single governance authority)",
        "u_list_empty": "no identities yet — run: tradraig user create --email you@corp.com --plan institutional",
        "u_api_down": "API down",
        "ex_started": "exercise started in-process (watch the board)",
        "dr_backup_ok": "backup created",
        "dr_restore_ok": "restore ok",
        "dr_restore_refused": "restore refused",
        "pay_api_down": "payments API down",
        "pay_charge_ok": "charge submitted",
        "pay_charge_locked": "charge gated (live providers locked)",
        "pay_refund_ok": "refunded",
        "pay_unknown": "unknown pay action",
        "ch_api_down": "challenge API down",
        "ch_unknown": "unknown challenge action",
        "ch_buy_pending": "charge created — activation happens when billing confirms it",
        "ch_buy_ok": "challenge service active",
        "ch_entitled": "entitled",
        "ch_not_entitled": "not entitled",
        "ch_buy_hint": "buy it with: tradraig challenge buy --user <id>",
        "ch_no_policy": "no policy registered for this account",
        "ch_no_user": "no acting identity; pass --user <id>",
    },
    "ar": {
        "layer": "الطبقة", "state": "الحالة", "detail": "التفصيل",
        "healthy": "سليم", "degraded": "متدهور", "disconnected": "منقطع",
        "error": "خطأ", "up": "يعمل",
        "api": "الواجهة (حوكمة)", "dash": "لوحة التحكم",
        "ai": "بوابة الذكاء/دسباي", "ollama": "أولاما (نموذج محلي)",
        "storage": "التخزين", "corpus": "مصدر البيانات",
        "registry": "سجل البرامج", "checks": "فحوصات",
        "pass": "ناجح", "warn_label": "تحذير", "fail": "فاشل", "hint": "عالج:",
        "gate_on": "بوابة دسباي مفعّلة (مثبّتة على مستوى المستخدم)",
        "gate_off": "بوابة دسباي معطّلة (مثبّتة على مستوى المستخدم)",
        "gate_note": "الواجهة القائمة تحتفظ ببيئتها حتى تُعاد تشغيلها",
        "proposal_ok": "تحدّث ملف الاقتراح", "proposal_missing": "لا يوجد مرشّح مُجمَّع بعد",
        "board": "مغذّيات مركز القيادة",
        "f_regime": "نظام السوق", "f_theses": "الأطروحات", "f_queue": "قائمة الترقية",
        "f_risk": "تحذيرات المخاطر", "f_paper": "تنفيذ الورق", "f_health": "صحة النظام",
        "f_validation": "تقارير التصديق", "f_observations": "الملاحظات",
        "f_learning": "سجل التعلم", "f_audit": "التدقيق",
        "f_plan": "خطة المشترك", "f_riskstate": "حالة المخاطر",
        "f_recommendations": "التوصيات", "f_chart_tf": "أطر الرسم",
        "f_chart_ctx": "سياق الرسم",
        "live": "حيّ", "empty": "فارغ", "static": "ثابت", "missing": "ناقص",
        "down": "متوقف", "board_note": "ثابت متوقع (بلا طابور محرك حي)",
        "u_created": "أُنشئت الهوية", "u_create_offline": "الواجهة متوقفة — إنشاء الهوية يتطلب الخادم (سلطة حوكمة واحدة)",
        "u_list_empty": "لا هويات بعد — نفّذ: tradraig user create --email you@corp.com --plan institutional",
        "u_api_down": "الواجهة متوقفة",
        "ex_started": "بدأ التمرين داخل العملية (تابع اللوحة)",
        "dr_backup_ok": "تم إنشاء النسخة الاحتياطية",
        "dr_restore_ok": "تمت الاستعادة",
        "dr_restore_refused": "رُفضت الاستعادة",
        "pay_api_down": "واجهة المدفوعات متوقفة",
        "pay_charge_ok": "تم إرسال الرسوم",
        "pay_charge_locked": "الرسوم محظورة (الدفع الحي مقفول)",
        "pay_refund_ok": "تمت الاسترداد",
        "pay_unknown": "إجراء دفع غير معروف",
        "ch_api_down": "واجهة التحدي متوقفة",
        "ch_unknown": "إجراء تحدٍ غير معروف",
        "ch_buy_pending": "تم إنشاء الرسوم — التفعيل عند تأكيد الفوترة",
        "ch_buy_ok": "خدمة إدارة الحساب مُفعّلة",
        "ch_entitled": "مُخوَّل",
        "ch_not_entitled": "غير مُخوَّل",
        "ch_buy_hint": "للشراء: tradraig challenge buy --user <id>",
        "ch_no_policy": "لا توجد سياسة مسجّلة لهذا الحساب",
        "ch_no_user": "لا توجد هوية فاعلة؛ مرّر --user <id>",
    },
}


# --------------------------------------------------------------------------- #
# low-level helpers
# --------------------------------------------------------------------------- #

def _try_reconfigure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def user_env(name: str) -> Optional[str]:
    """Windows User-registry env fallback (best effort)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            value, _ = winreg.QueryValueEx(k, name)
            return str(value)
    except Exception:
        return None


def _write_user_env(name: str, value: str) -> bool:
    """Persist a User-scope env var (Windows) and mirror it in this process."""
    wrote = False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        wrote = True
    except Exception:
        pass
    os.environ[name] = value
    return wrote


def env(name: str) -> Optional[str]:
    return os.environ.get(name) or user_env(name)


def port_listening(port: int, timeout: float = 0.8) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def http_json(url: str, timeout: float = 2.5) -> Tuple[bool, Any]:
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return False, str(exc)


def _session_token() -> str:
    """A human session token for the console, when one is configured.

    Preferred over the service token because the service token is now scoped to
    the machine rails: it drives the engine/venue lifecycle, but a human command
    (`user create`, `pay charge`, `strategy propose`) that mutates state needs a
    real session. The token is issued by `tradraig login` and exported as
    `TRADERAIG_SESSION_TOKEN` (or stored in the vault slot `auth.session_token`).
    """
    token = os.environ.get("TRADERAIG_SESSION_TOKEN", "").strip()
    if not token:
        try:
            from core.secrets_vault import vault
            token = (vault.read("auth.session_token") or "").strip()
        except Exception:
            token = ""
    return token


def service_headers() -> Dict[str, str]:
    """Auth header for the console: a session if we have one, else the machine token.

    The console is a privileged operator tool. With `TRADERAIG_AUTH=1` a session
    authenticates the operator on every route, while the service token
    authenticates only the machine rails (it is no longer a universal pass — a
    leaked machine credential must not mint entitlements or move money). Sending
    nothing (and letting the API explain why) is better than sending a token
    that might be wrong.
    """
    session = _session_token()
    if session:
        return {"Authorization": f"Bearer {session}"}
    token = os.environ.get("AUTH_SERVICE_TOKEN", "").strip()
    if not token:
        try:
            from core.secrets_vault import vault
            token = (vault.read("auth.service_token") or "").strip()
        except Exception:
            token = ""
    return {"X-Service-Token": token} if token else {}


def http_post_json(url: str, payload: Dict[str, Any],
                   timeout: float = 5.0, method: str = "POST"
                   ) -> Tuple[Optional[int], Any]:
    import urllib.error
    import urllib.request
    headers = {"Content-Type": "application/json"}
    headers.update(service_headers())
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = str(exc)
        return exc.code, body
    except Exception as exc:
        return None, str(exc)


def feed_probe(url: str, timeout: float = 4.0) -> Dict[str, Any]:
    """Probe one dashboard feed: status-code, payload size, kind."""
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read()
            status = int(resp.status)
            return {
                "status": status,
                "bytes": len(body),
                "kind": "empty" if len(body) < 4 else "live",
            }
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "bytes": 0,
                "kind": "static" if exc.code == 404 else "missing"}
    except Exception:
        return {"status": None, "bytes": 0, "kind": "down"}


def dir_size_gb(path: str) -> float:
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    except OSError:
        return 0.0
    return round(total / 1024 ** 3, 2)


def free_ram_gb() -> float:
    try:
        class M(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = M()
        m.dwLength = ctypes.sizeof(M)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(m.ullAvailPhys / 1024 ** 3, 2)
    except Exception:
        return -1.0


def pid_on_port(port: int) -> Optional[int]:
    """Find the PID listening on `port` via netstat (Windows)."""
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            timeout=4).stdout or ""
    except Exception:
        return None
    for line in out.splitlines():
        if ("LISTENING" in line and f":{port} " in line):
            parts = line.split()
            if parts:
                pid = parts[-1]
                if pid.isdigit():
                    return int(pid)
    return None


_LOG_HANDLES: List[Any] = []


def _start_detached(cmd: List[str], cwd: str, log_name: str,
                    extra_env: Optional[Dict[str, str]] = None) -> int:
    os.makedirs(LOG_DIR, exist_ok=True)
    out = open(os.path.join(LOG_DIR, f"{log_name}.out.log"), "ab")
    err = open(os.path.join(LOG_DIR, f"{log_name}.err.log"), "ab")
    _LOG_HANDLES.append(out)  # keep refs: preserve child log pipes
    _LOG_HANDLES.append(err)
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    flags = getattr(subprocess, "DETACHED_PROCESS", 0)
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=out, stderr=err,
                            stdin=subprocess.DEVNULL, creationflags=flags,
                            close_fds=True)
    return proc.pid


# --------------------------------------------------------------------------- #
# probes -> snapshot (pure data, no printing)
# --------------------------------------------------------------------------- #

def _dspy_env() -> Dict[str, str]:
    return {k: v for k in LM_ENVS if (v := env(k))}


def _ollama_models() -> List[str]:
    ok, payload = http_json(f"http://127.0.0.1:{OLLAMA_PORT}/api/tags")
    if not ok or not isinstance(payload, dict):
        return []
    return [m.get("name", "?") for m in payload.get("models", [])]


def _api_health() -> Dict[str, Any]:
    ok, payload = http_json(f"http://127.0.0.1:{API_PORT}/health")
    return {"ok": ok, "payload": payload}


def _dspy_status() -> Dict[str, Any]:
    ok, payload = http_json(f"http://127.0.0.1:{API_PORT}/research/dspy/status")
    return {"ok": ok, "payload": payload}


def _registry_count() -> Optional[int]:
    ok, payload = http_json(f"http://127.0.0.1:{API_PORT}/research/dspy/registry")
    if not ok or not isinstance(payload, dict):
        return None
    versions = payload.get("programs") or payload.get("versions") or []
    if isinstance(versions, list):
        return len(versions)
    return None


def _corpus_info() -> Dict[str, Any]:
    from ai.dspy.datasets.strategy_lab import corpus_summary  # local, dspy-free
    try:
        raw = corpus_summary()
        total = 0
        for symbol, info in (raw or {}).items():
            if isinstance(info, dict):
                total += int(info.get("observations", 0) or 0)
        return {"total_observations": total, "per_symbol": raw or {}}
    except Exception as exc:
        return {"error": str(exc)}


def snapshot() -> Dict[str, Any]:
    """Aggregate every probe into one plain dict (never raises)."""
    api = _api_health()
    dash = port_listening(DASH_PORT)
    ollama_models = _ollama_models()
    ollama_up = bool(ollama_models)
    dspy = _dspy_status()
    reg = _registry_count()
    gate = env(GATE_ENV) == "1"
    provider_key = bool(env("OPENAI_API_KEY") or env("ANTHROPIC_API_KEY")
                        or env("TRADERAIG_DSPY_LM_API_KEY"))
    corpus = _corpus_info()
    dspy_installed = importlib.util.find_spec("dspy") is not None
    try:
        dspy_version = importlib.metadata.version("dspy")
    except Exception:
        dspy_version = "?"
    return {
        "api": api,
        "dashboard": {"up": dash, "port": DASH_PORT},
        "ollama": {"up": ollama_up, "port": OLLAMA_PORT,
                   "models": ollama_models},
        "dspy": {
            "gate": gate,
            "provider_key": provider_key,
            "enabled": gate and provider_key and dspy_installed,
            "live": dspy["ok"],
            "live_status": dspy["payload"] if dspy["ok"] else None,
            "installed": dspy_installed,
            "version": dspy_version,
            "registry_count": reg,
            "configured": _dspy_env(),
        },
        "corpus": corpus,
        "storage": {
            "ollama_models_gb": dir_size_gb(OLLAMA_MODELS_DIR),
            "path": OLLAMA_MODELS_DIR,
        },
        "system": {
            "free_ram_gb": free_ram_gb(),
            "dspy_layer_dir": "ai/dspy",
        },
    }


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

def _st(state: bool, lang: str, degraded: bool = False) -> str:
    """Human state string with color."""
    t = I18N[lang]
    if state:
        return _ansi("ok") + t["up"] + _ansi("off")
    return _ansi("warn" if degraded else "bad") + t["down"] + _ansi("off")


def _ansi(which: str) -> str:
    return _ANSI[which]


def render_status(snap: Dict[str, Any], lang: str) -> str:
    t = I18N[lang]
    lines: List[str] = []
    lines.append(f"{_ansi('bold')}TraderAIG :: {t['layer']} / {t['state']} / {t['detail']}{_ansi('off')}")
    api_up = snap["api"]["ok"]
    lines.append(f"{t['api']:26} {_st(api_up, lang):8} "
                 f"{snap['api']['payload'].get('status', '?') if api_up else 'no listener on ' + str(API_PORT)}")
    dash_up = snap["dashboard"]["up"]
    lines.append(f"{t['dash']:26} {_st(dash_up, lang):8} {(':' + str(DASH_PORT)) if dash_up else 'offline'}")
    ol = snap["ollama"]
    lines.append(f"{t['ollama']:26} {_st(ol['up'], lang):8} "
                 f"{', '.join(ol['models']) if ol['up'] else 'server down'}")
    d = snap["dspy"]
    live = d["live_status"]
    live_enabled = bool(live) and bool(live.get("enabled") is True
                           or str(live.get("enabled") or "").lower() == "true")
    if live and "enabled" in live:
        state_ok = live_enabled
        if live_enabled:
            enabled = "enabled"
            if not d["enabled"]:
                enabled += " :: local gate OFF (workers spawned here refused)"
        else:
            reason = live.get("reason") or "off"
            enabled = f"off ({reason})"
    else:
        state_ok = d["enabled"]
        enabled = ("enabled" if d["enabled"]
                   else "GATE OFF" if not d["gate"]
                   else "needs provider key")
    live_txt = ""
    if live:
        lm = live.get("lm", {})
        live_txt = f"provider={lm.get('provider', '?')}, model={lm.get('model') or '-'}"
    lines.append(f"{t['ai']:26} {_st(state_ok, lang, degraded=bool(not d['gate'])):8} "
                 f"{'dspy ' + d['version'] + ' :: ' + enabled + (' :: ' + live_txt if live_txt else '')}")
    reg = d["registry_count"]
    lines.append(f"{t['registry']:26} {_st(reg is not None, lang):8} "
                 f"{f'{reg} candidates' if reg is not None else 'API offline'}")
    corpus = snap["corpus"]
    if isinstance(corpus, dict) and "total_observations" in corpus:
        per = corpus.get("per_symbol", {})
        symbols = ", ".join(f"{k}:{v.get('observations', 0)}" for k, v in per.items())
        lines.append(f"{t['corpus']:26} --            {corpus['total_observations']} observations ({symbols})")
    else:
        lines.append(f"{t['corpus']:26} --            {corpus.get('error', 'n/a') if isinstance(corpus, dict) else 'n/a'}")
    stg = snap["storage"]
    lines.append(f"{t['storage']:26} --            {stg['ollama_models_gb']} GB on {stg['path']} "
                 f"({'ok' if free_ram_gb() >= 1.0 else 'low RAM'})")
    lines.append(f"system         --            free RAM {snap['system']['free_ram_gb']} GB")
    return "\n".join(lines)


def render_health_json(snap: Dict[str, Any]) -> str:
    return json.dumps(snap, indent=1, default=str)


def doctor(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Pure check list built purely from the snapshot."""
    checks: List[Dict[str, Any]] = []
    checks.append({
        "label": "API on :8000", "ok": snap["api"]["ok"],
        "detail": "run: python main.py  (or: tradraig start backend)",
        "degraded": False,
    })
    checks.append({"label": "Dashboard on :8443", "ok": snap["dashboard"]["up"],
                   "detail": "run in TAIG Dash: npm run dev", "degraded": True})
    checks.append({"label": "Ollama server", "ok": snap["ollama"]["up"],
                   "detail": "start: tradraig start ollama", "degraded": False})
    models = snap["ollama"]["models"]
    if models:
        checks.append({"label": f"Local models ({len(models)})", "ok": True,
                       "detail": ", ".join(models), "degraded": False})
    d = snap["dspy"]
    checks.append({"label": "dspy installed", "ok": d["installed"],
                   "detail": "pip install -r requirements-ai.txt",
                   "degraded": False})
    live_enabled = bool(d["live_status"]) and bool(d["live_status"].get("enabled"))
    gate_ok = bool(d["gate"]) or bool(d["live"] and live_enabled)
    checks.append({
        "label": "DSPy gate / backend",
        "ok": gate_ok,
        "detail": ("live backend reports enabled" if gate_ok and not d["gate"]
                   else "set TRADERAIG_DSPY_ENABLED=1 (or: tradraig start backend)"),
        "degraded": not gate_ok,
    })
    checks.append({"label": "Provider key configured",
                   "ok": bool(d["provider_key"]),
                   "detail": "OPENAI_API_KEY / ANTHROPIC_API_KEY / "
                             "TRADERAIG_DSPY_LM_API_KEY", "degraded": False})
    checks.append({"label": "DSPy live API", "ok": d["live"],
                   "detail": "/research/dspy/status reachable",
                   "degraded": True})
    checks.append({"label": "Model swap configured",
                   "ok": bool(d["configured"]),
                   "detail": ", ".join(f"{k}={v}" for k, v in d["configured"].items())
                             or "TRADERAIG_DSPY_LM=https://...",
                   "degraded": False})
    return {"checks": checks}


def render_doctor(res: Dict[str, Any], lang: str) -> str:
    t = I18N[lang]
    lines = [f"{_ansi('bold')}TraderAIG :: {t['layer']} {t['checks']}{_ansi('off')}"]
    for c in res["checks"]:
        if c["ok"]:
            mark = _ansi("ok") + t["pass"] + _ansi("off")
        elif c.get("degraded"):
            mark = _ansi("warn") + t["warn_label"] + _ansi("off")
        else:
            mark = _ansi("bad") + t["fail"] + _ansi("off")
        lines.append(f"  {mark}  {c['label']:<28} {_ansi('dim')}{c['detail']}{_ansi('off')}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def cmd_status(args: argparse.Namespace) -> int:
    snap = snapshot()
    if args.json:
        print(render_health_json(snap))
    else:
        print(render_status(snap, args.lang))
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    """Open a session for the console — the human credential (28.19).

    With enforcement on, a human command (`user create`, `pay charge`, `strategy
    propose`) needs a session: the service token is now scoped to the machine
    rails and will not satisfy a human mutation. The token is printed for the
    operator to export; the password is never stored or echoed.
    """
    import getpass
    base = f"http://127.0.0.1:{API_PORT}"
    email = (args.email or os.environ.get("IDENTITY_PRIMARY_EMAIL", "")).strip()
    if not email:
        print(f"{_ANSI['bad']}login requires --email (or IDENTITY_PRIMARY_EMAIL)"
              f"{_ANSI['off']}")
        return 1
    password = args.password or getpass.getpass("password: ")
    rc, data = http_post_json(f"{base}/auth/login",
                              {"email": email, "password": password})
    if rc != 200 or not isinstance(data, dict) or not data.get("token"):
        print(f"{_ANSI['bad']}login failed ({rc}){_ANSI['off']}")
        return 1
    token = data["token"]
    print(f"{_ANSI['ok']}session opened{_ANSI['off']} for {data.get('user_id')}")
    print(token)
    print(f"{_ANSI['dim']}export TRADERAIG_SESSION_TOKEN={token}"
          f"{_ANSI['off']}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    res = doctor(snapshot())
    hard_failures = [c for c in res["checks"] if not c["ok"] and not c.get("degraded")]
    if args.json:
        print(json.dumps({
            "ok": not hard_failures,
            "failed": [c["label"] for c in hard_failures],
            "checks": res["checks"],
        }, indent=1, default=str))
    else:
        print(render_doctor(res, args.lang))
    return 1 if hard_failures else 0


def cmd_start(args: argparse.Namespace) -> int:
    targets = args.target.split(",")
    pids = []
    if "all" in targets or "backend" in targets:
        env_extra = {}
        if _dspy_env():
            env_extra = {"TRADERAIG_DSPY_ENABLED": "1", **_dspy_env()}
        pid = _start_detached([sys.executable, "main.py"], ROOT, "backend", env_extra)
        pids.append(("backend", pid))
    if "all" in targets or "dash" in targets:
        # `preview` serves the verified `dist/` build, not the vite dev server:
        # the dev server keeps HMR and the figma/Storybook middlewares loaded,
        # which is the wrong thing to leave running unattended for 24/7. The
        # tsc + vite build half belongs to the verification gate, not here.
        pid = _start_detached(["node", "node_modules/vite/bin/vite.js", "preview",
                               "--port", str(DASH_PORT), "--strictPort",
                               "--host", "0.0.0.0"],
                              DASH_DIR, "dash", {"PORT": str(DASH_PORT)})
        pids.append(("dashboard", pid))
    if "all" in targets or "ollama" in targets:
        extra = {"OLLAMA_MODELS": OLLAMA_MODELS_DIR} if os.path.isdir(OLLAMA_MODELS_DIR) else {}
        pid = _start_detached([OLLAMA_EXE, "serve"], ROOT, "ollama", extra)
        pids.append(("ollama", pid))
    for name, pid in pids:
        print(f"{name}: pid {pid} (logs in {LOG_DIR})")
    if not pids:
        print("targets: backend|dash|ollama|all")
        return 2
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    target = args.target
    port = API_PORT if target == "backend" else DASH_PORT if target == "dash" else OLLAMA_PORT
    pid = pid_on_port(port)
    if pid is None:
        print(f"{target}: nothing listening on :{port}")
        return 0
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True, timeout=10)
        time.sleep(1.0)
        left = pid_on_port(port)
        print(f"{target}: stopped pid {pid}" + ("" if left is None else f" (still on :{port} pid {left})"))
    except Exception as exc:
        print(f"{target}: {exc}")
        return 1
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    pytest = [sys.executable, "-m", "pytest"]
    if args.fast:
        pytest.append(os.path.join("tests", "test_ai_dspy", "test_ai_dspy.py"))
    else:
        pytest.append("-q")
    proc = subprocess.run(pytest, cwd=ROOT, timeout=args.timeout)
    return proc.returncode


def _save_proposal(program: str) -> dict:
    from ai.dspy.intake import save_proposal  # dspy-free import
    return save_proposal(program)


def cmd_dspy(args: argparse.Namespace) -> int:
    if args.action == "status":
        if args.json:
            ok, payload = http_json(
                f"http://127.0.0.1:{API_PORT}/research/dspy/status", timeout=4)
            if not ok:
                from ai.dspy.runtime import status as _status  # local, dspy-free
                payload = _status()
            print(json.dumps(payload, indent=1, default=str))
            return 0
        # offline-safe local snapshot (never imports dspy)
        from ai.dspy.runtime import status as _status
        from ai.dspy.models import catalog
        snap = _status()
        print("enabled        :", snap["enabled"])
        print("reason         :", snap["reason"] or "-")
        print("dspy           :", f"{snap['dspy_version']} (installed={snap['dspy_installed']})")
        print("lm             :", json.dumps(snap["lm"], default=str))
        cat = catalog()
        print("models         :", ", ".join(m["name"] for m in cat["models"]) or "n/a")
        print("configured     :", json.dumps(cat["configured"], default=str))
        reg = (snap.get("sources") or {}).get("registry") or {}
        reg_count = (reg.get("count") if isinstance(reg, dict) else None) \
            or _registry_count()
        print("registry       :", f"{reg_count} candidates" if reg_count is not None else "-")
        return 0
    if args.action == "models":
        from ai.dspy.models import catalog
        print(render_health_json(catalog()))
        return 0
    if args.action == "proposal":
        t = I18N[args.lang]
        try:
            doc = _save_proposal(args.program)
        except Exception as exc:
            print(f"proposal failed: {exc}")
            return 1
        if not doc.get("candidate"):
            print(f"{_ANSI['warn']}{t['proposal_missing']}{_ANSI['off']}")
            return 2
        d = doc.get("dossier") or {}
        print(json.dumps({
            "proposal": doc.get("proposal_file"),
            "candidate": doc.get("candidate"),
            "compiled": d.get("compiled_score"),
            "baseline": d.get("baseline_score"),
            "delta": d.get("delta_vs_baseline"),
            "serialized": d.get("serialized_artifact"),
        }, indent=1, default=str))
        print(f"{_ANSI['ok']}{t['proposal_ok']}{_ANSI['off']}")
        return 0
    if args.action == "optimize":
        env_extra = _dspy_env()
        if args.model:
            env_extra["TRADERAIG_DSPY_LM"] = args.model
        env_extra["TRADERAIG_DSPY_ENABLED"] = "1"
        cmd = [sys.executable, "-m", "ai.dspy.worker", "optimize",
               "--programs", args.program, "--trials", str(args.trials), "--sleep", "0"]
        pid = _start_detached(cmd, ROOT, "dspy-optimize", env_extra)
        print(f"optimize dispatched pid {pid} (program={args.program}, trials={args.trials}, model={args.model or env_extra.get('TRADERAIG_DSPY_LM')})")
        print(f"watch log: {LOG_DIR}")
        return 0
    print("dspy: status | models | optimize --model M --trials N | proposal [--program P]")
    return 2


def cmd_gate(args: argparse.Namespace) -> int:
    t = I18N[args.lang]
    value = "1" if args.state == "on" else "0"
    persisted = _write_user_env(GATE_ENV, value)
    label = t["gate_on"] if value == "1" else t["gate_off"]
    ansi = _ANSI["ok"] if value == "1" else _ANSI["warn"]
    print(f"{ansi}{label}{_ANSI['off']}{' (persisted)' if persisted else ' (session only)'}")
    print(f"{_ANSI['dim']}{t['gate_note']}{_ANSI['off']}")
    return 0 if persisted else 1


def cmd_info(args: argparse.Namespace) -> int:
    print(f"python    : {sys.version.split()[0]}")
    try:
        print(f"dspy      : {importlib.metadata.version('dspy')}")
    except Exception:
        print("dspy      : not installed")
    try:
        print(f"fastapi   : {importlib.metadata.version('fastapi')}")
    except Exception:
        print("fastapi   : ?")
    try:
        print(f"numpy     : {importlib.metadata.version('numpy')}")
    except Exception:
        print("numpy     : ?")
    print(f"gate      : TRADERAIG_DSPY_ENABLED={'1' if env(GATE_ENV) == '1' else '0'}"
          f" ({env(GATE_ENV) or 'default off'})")
    conf = _dspy_env()
    print(f"lm env    : {conf or '(none - use: tradraig dspy optimize --model llama3.2:1b)'}")
    print(f"free RAM  : {free_ram_gb()} GB")
    print(f"local mods: {OLLAMA_MODELS_DIR} = {dir_size_gb(OLLAMA_MODELS_DIR)} GB")
    return 0


def cmd_board(args: argparse.Namespace) -> int:
    """Probe every read-only feed the dashboard depends on; verdict per widget."""
    t = I18N[args.lang]
    rows = []
    for key, path in BOARD_FEEDS:
        probe = feed_probe(f"http://127.0.0.1:{API_PORT}{path}")
        rows.append({
            "feed": t[key], "path": path,
            "status": probe["status"], "bytes": probe["bytes"],
            "kind": probe["kind"],
        })
    if args.json:
        print(json.dumps({
            "live": [r["feed"] for r in rows if r["kind"] == "live"],
            "empty": [r["feed"] for r in rows if r["kind"] == "empty"],
            "static": [r["feed"] for r in rows if r["kind"] == "static"],
            "missing": [r["feed"] for r in rows if r["kind"] == "missing"],
            "down": [r["feed"] for r in rows if r["kind"] == "down"],
            "feeds": rows,
        }, indent=1, default=str))
    else:
        print(f"{_ansi('bold')}{t['board']}{_ansi('off')}")
        for r in rows:
            status = str(r["status"]) if r["status"] else t["down"]
            mark = _ansi("ok") if r["kind"] == "live" else \
                _ansi("warn") if r["kind"] in ("empty", "static") else _ansi("bad")
            print(f"  {mark}{r['kind'].ljust(7)}{_ansi('off')} {status:<6} "
                  f"{str(r['bytes'])+'B':<8} {r['feed'] + ' ' + _ansi('dim') + r['path'] + _ansi('off')}")
        if any(r["feed"] == t["f_paper"] and r["kind"] == "static" for r in rows):
            print(f"{_ansi('dim')}{t['board_note']}: /paper/requests{_ansi('off')}")
    core = [r for r in rows if r["feed"] in (t["f_regime"], t["f_theses"], t["f_risk"], t["f_health"])]
    return 0 if all(r["kind"] in ("live", "empty") for r in core) else 1


def cmd_user(args: argparse.Namespace) -> int:
    """Identity ops — always via the API (single Governance OS authority)."""
    t = I18N[args.lang]
    base = f"http://127.0.0.1:{API_PORT}"
    if args.action == "create":
        rc, payload = http_post_json(f"{base}/users", {
            "email": args.email,
            "display_name": getattr(args, "display", "") or "",
            "plan": args.plan,
        })
        if rc == 201:
            print(f"{_ANSI['ok']}{t['u_created']}{_ANSI['off']} "
                  f"{payload.get('user_id', '')} {payload.get('email', '')} -> {payload.get('plan', '')}")
            return 0
        if rc is None:
            print(f"{_ANSI['bad']}{t['u_create_offline']}{_ANSI['off']}")
            return 1
        print(f"HTTP {rc}: {payload}")
        return 1
    ok, data = http_json(f"{base}/users")
    if not ok:
        print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
        return 1
    users = data if isinstance(data, list) else []
    if not users:
        print(f"{_ANSI['dim']}{t['u_list_empty']}{_ANSI['off']}")
        return 0
    for u in users:
        print(f"  {str(u.get('user_id', ''))[:8]:<10} {u.get('email', ''):<28} "
              f"{str(u.get('plan', '')):<14} {u.get('status', '')}")
    return 0


def cmd_exercise(args: argparse.Namespace) -> int:
    t = I18N[args.lang]
    base = f"http://127.0.0.1:{API_PORT}"
    if getattr(args, "status", False):
        ok, data = http_json(f"{base}/ops/exercise")
        if not ok:
            print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
            return 1
        print(json.dumps(data, indent=1, default=str))
        return 0
    secs = float(getattr(args, "seconds", 20.0))
    rc, payload = http_post_json(f"{base}/ops/exercise?seconds={secs}", {})
    if rc == 409:
        print(f"{_ANSI['warn']}already running: {payload}{_ANSI['off']}")
        return 1
    if rc != 200:
        print(f"{_ANSI['bad']}{t['u_api_down'] if rc is None else f'HTTP {rc}'}{_ANSI['off']}")
        return 1
    print(f"{_ANSI['ok']}{t['ex_started']}{_ANSI['off']} ({secs}s, running={payload.get('running')})")
    return 0


def cmd_change(args: argparse.Namespace) -> int:
    """Change Governance — always via the API (single authority + audit)."""
    t = I18N[args.lang]
    base = f"http://127.0.0.1:{API_PORT}"
    act = args.action
    if act == "submit":
        rc, payload = http_post_json(f"{base}/governance/change-requests", {
            "kind": args.kind, "target": args.target, "reason": args.reason,
            "requested_by": "operator",
        })
        if rc == 400:
            print(f"{_ANSI['bad']}HTTP {rc}: {payload}{_ANSI['off']}")
            return 1
        if rc is None:
            print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
            return 1
        req = payload.get("request", {})
        print(f"{_ANSI['ok']}change {req.get('id', '?')} submitted "
              f"[{args.kind}@{args.target}] pending{_ANSI['off']}")
        return 0
    if act == "list":
        ok, data = http_json(f"{base}/governance/change-requests"
                             + (f"?status={args.status}" if args.status else ""))
        if not ok:
            print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
            return 1
        rows = data.get("requests", [])
        if not rows:
            print(f"{_ANSI['dim']}no change requests{_ANSI['off']}")
            return 0
        for r in rows:
            print(f"  {str(r.get('id', '')):<13} {str(r.get('status', '')):<9} "
                  f"{str(r.get('kind', '')):<10} {str(r.get('target', '')):<14} "
                  f"by={r.get('requested_by', '')[:8]}")
        return 0
    path = f"{base}/governance/change-requests/{args.id}/{act}"
    payload = {"decided_by": getattr(args, "decided_by", args.id and "operator")}
    if act == "deny":
        payload["reason"] = getattr(args, "reason", "")
    if act == "cancel":
        payload = {"requested_by": getattr(args, "requested_by", "operator")}
    rc, data = http_post_json(path, payload)
    if rc == 409:
        print(f"{_ANSI['warn']}HTTP 409: {data}{_ANSI['off']}")
        return 1
    if rc != 200:
        print(f"{_ANSI['bad']}{t['u_api_down'] if rc is None else f'HTTP {rc}: {data}'}{_ANSI['off']}")
        return 1
    stage = data.get("to_stage")
    tail = f" -> {stage}" if stage else ""
    print(f"{_ANSI['ok']}change {args.id} {act}ed [{data.get('status')}]{tail}{_ANSI['off']}")
    return 0


def _print_vet(vet: Dict[str, Any]) -> None:
    if not vet:
        return
    verdict = str(vet.get("verdict", ""))
    if verdict == "PASS":
        fam = vet.get("family")
        print(f"  {_ANSI['ok']}verdict PASS{_ANSI['off']} family={fam} "
              f"tf={vet.get('htf_tf')}/{vet.get('setup_tf')}/{vet.get('trigger_tf')} "
              f"trigger={vet.get('trigger_model')} exit={vet.get('exit_model')} "
              f"params={vet.get('params')}")
    else:
        print(f"  {_ANSI['warn'] if verdict == 'REVISE' else _ANSI['bad']}"
              f"verdict {verdict}{_ANSI['off']}")
        for r in vet.get("reasons", []):
            print(f"    - {r}")
    for w in vet.get("warnings", []):
        print(f"  {_ANSI['dim']}warn: {w}{_ANSI['off']}")


def cmd_strategy(args: argparse.Namespace) -> int:
    """User strategy intake — describe -> vet -> test -> governed promote.

    The user describes a strategy in words; the project scrutinizes it
    immediately (top-level VetEngine), then tests it through the lab
    pipeline; a passing test registers it (RESEARCH/CANDIDATE) and further
    promotion rides the governed ladder (engine-safety guard lives in the
    API). Console commands only ever call the API (single authority).
    """
    t = I18N[args.lang]
    base = f"http://127.0.0.1:{API_PORT}"
    act = args.action

    def _hints(p: argparse.Namespace) -> Dict[str, Any]:
        hints: Dict[str, Any] = {}
        for flag, key in (("family", "family"), ("trigger", "trigger_model"),
                          ("exit", "exit_model")):
            val = getattr(p, flag, "")
            if val:
                hints[key] = val
        if getattr(p, "min_rr", None) is not None:
            hints["min_rr"] = p.min_rr
        if getattr(p, "session", ""):
            hints["sessions"] = [p.session]
        return hints

    if act == "propose":
        payload = {"description": args.text, "requested_by": args.by,
                   "asset": args.asset}
        payload.update(_hints(args))
        rc, data = http_post_json(f"{base}/strategies/intake", payload,
                                  timeout=10.0)
        if rc is None:
            print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
            return 1
        if rc != 200:
            print(f"{_ANSI['bad']}HTTP {rc}: {data}{_ANSI['off']}")
            return 1
        entry = data.get("entry", {})
        print(f"{_ANSI['ok']}strategy {entry.get('id')} proposed — "
              f"{entry.get('status')}{_ANSI['off']}")
        _print_vet(entry.get("vet"))
        return 0

    if act == "vet":
        payload = _hints(args)
        rc, data = http_post_json(
            f"{base}/strategies/intake/{args.id}/vet", payload, timeout=10.0)
        if rc is None:
            print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
            return 1
        if rc != 200:
            print(f"{_ANSI['bad']}HTTP {rc}: {data}{_ANSI['off']}")
            return 1
        print(f"{_ANSI['ok']}strategy {args.id} re-vetted{_ANSI['off']}")
        _print_vet(data.get("vet"))
        return 0

    if act == "test":
        rc, data = http_post_json(
            f"{base}/strategies/intake/{args.id}/test",
            {"source": args.source, "count": args.count,
             "cost_r": args.cost_r}, timeout=args.timeout)
        if rc == 409 or rc == 400:
            print(f"{_ANSI['warn']}HTTP {rc}: {data}{_ANSI['off']}")
            return 1
        if rc is None:
            print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
            return 1
        if rc != 200:
            print(f"{_ANSI['bad']}HTTP {rc}: {data}{_ANSI['off']}")
            return 1
        res = data.get("result", {})
        rep = res.get("report", {})
        print(f"{_ANSI['ok']}tested {res.get('strategy_id')} — "
              f"{res.get('trades')} trades, stage={res.get('stage')}{_ANSI['off']}")
        print(f"  {res.get('source')} source, {res.get('count')} bars, "
              f"{res.get('elapsed_seconds')}s, cost_r={res.get('cost_r')}")
        mark = "PASS" if rep.get("passed") else "FAIL"
        print(f"  validation [{mark}]: samples={rep.get('samples')} "
              f"EV={rep.get('expected_value')} PF={rep.get('profit_factor')} "
              f"OOS_ev={rep.get('oos_ev')} dd={rep.get('max_drawdown')}")
        failed = [g for g, ok in (rep.get("gates") or {}).items() if not ok]
        if failed:
            print(f"  {_ANSI['warn']}failed gates: {', '.join(failed)}"
                  f"{_ANSI['off']}")
        return 0

    if act == "list":
        ok, data = http_json(f"{base}/strategies/intake"
                             + (f"?status={args.status}" if args.status else ""))
        if not ok:
            print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
            return 1
        rows = data.get("entries", [])
        if not rows:
            print(f"{_ANSI['dim']}no strategy intake entries{_ANSI['off']}")
            return 0
        for e in rows:
            vet = e.get("vet") or {}
            print(f"  {str(e.get('id', '')):<12} {str(e.get('status', '')):<9} "
                  f"{str(vet.get('family') or '-'):<34} "
                  f"{str(e.get('spec', {}).get('asset', '')):<8} "
                  f"by={str(e.get('requested_by', ''))[:8]}")
        return 0

    if act == "show":
        ok, data = http_json(f"{base}/strategies/intake/{args.id}")
        if not ok:
            print(f"{_ANSI['bad']}HTTP 404: intake entry not found"
                  f"{_ANSI['off']}")
            return 1
        entry = data.get("entry", {})
        spec = entry.get("spec", {})
        print(f"strategy {entry.get('id')} [{entry.get('status')}] "
              f"by={entry.get('requested_by')}")
        print(f"  asset={spec.get('asset')}  "
              f"description: {spec.get('description')}")
        _print_vet(entry.get("vet"))
        test = entry.get("test")
        if test:
            rep = test.get("report", {})
            mark = "PASS" if rep.get("passed") else "FAIL"
            print(f"  tested: {test.get('strategy_id')} stage={test.get('stage')} "
                  f"[{mark}] samples={rep.get('samples')} "
                  f"EV={rep.get('expected_value')} OOS_ev={rep.get('oos_ev')}")
            print(f"  sources: {test.get('source')} "
                  f"obs_file={test.get('observations_file')}")
        else:
            print(f"  {_ANSI['dim']}not tested yet{_ANSI['off']}")
        return 0

    if act == "promote":
        rc, data = http_post_json(
            f"{base}/strategies/intake/{args.id}/promote",
            {"requested_by": args.by}, timeout=10.0)
        if rc == 409:
            print(f"{_ANSI['warn']}HTTP 409: {data}{_ANSI['off']}")
            return 1
        if rc is None:
            print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
            return 1
        if rc != 200:
            print(f"{_ANSI['bad']}HTTP {rc}: {data}{_ANSI['off']}")
            return 1
        print(f"{_ANSI['ok']}{data.get('strategy_id')} promoted "
              f"{data.get('from')} -> {data.get('to')}{_ANSI['off']}")
        return 0

    print(f"{_ANSI['bad']}unknown strategy action: {act}{_ANSI['off']}")
    return 1


def cmd_pay(args: argparse.Namespace) -> int:
    """Billing & wallet — always via the API (single billing authority)."""
    t = I18N[args.lang]
    base = f"http://127.0.0.1:{API_PORT}"
    act = args.action

    def _down() -> int:
        print(f"{_ANSI['bad']}{t['pay_api_down']}{_ANSI['off']}")
        return 1

    if act == "status":
        ok, data = http_json(f"{base}/payments/status")
        if not ok:
            return _down()
        print(f"  mode={data.get('mode')} provider={data.get('provider')} "
              f"locked={data.get('locked')} "
              f"live_allowed={data.get('gate_live_allowed')}")
        print(f"  ledger: {data.get('ledger_succeeded')} succeeded / "
              f"{data.get('ledger_total')} total")
        print(f"  keys: configured={data.get('provider_configured')} "
              f"webhook={data.get('webhook_configured')}")
        return 0
    if act == "providers":
        ok, data = http_json(f"{base}/payments/providers")
        if not ok:
            return _down()
        for r in data.get("available", []):
            print(f"  {str(r['name']):<10} configured={r['configured']} "
                  f"live_wired={r['live_wired']}")
        print(f"selected: {data.get('selected')}")
        return 0
    if act == "charge":
        rc, data = http_post_json(f"{base}/payments/charge", {
            "user_id": args.user, "amount_usd": args.amount,
            "plan": getattr(args, "plan", "") or "",
            "provider": getattr(args, "provider", "") or "",
            "description": getattr(args, "description", "") or "",
        })
        if rc == 409:
            print(f"{_ANSI['warn']}{t['pay_charge_locked']}{_ANSI['off']}: {data}")
            return 1
        if rc is None:
            return _down()
        if rc != 200:
            print(f"{_ANSI['bad']}HTTP {rc}: {data}{_ANSI['off']}")
            return 1
        print(f"{_ANSI['ok']}{t['pay_charge_ok']}{_ANSI['off']}: "
              f"{data.get('charge_id')} {data.get('status')} "
              f"${data.get('amount_usd')} balance={data.get('wallet_balance')}")
        if data.get("subscription_activated"):
            print("  subscription activated via governance")
        return 0
    if act == "wallet":
        ok, data = http_json(f"{base}/payments/wallet/{args.user}")
        if not ok:
            return _down()
        print(f"  wallet {args.user}: balance=${data.get('balance_usd')} "
              f"(succeeded={data.get('succeeded')} "
              f"refunded={data.get('refunded')} pending={data.get('pending')})")
        for e in data.get("entries", [])[-5:]:
            print(f"    {str(e['status']):<9} ${e['amount_usd']:<8} "
                  f"{str(e['provider']):<8} {str(e['charge_id'])[:22]} "
                  f"{e.get('plan', '')}")
        return 0
    if act == "refund":
        rc, data = http_post_json(f"{base}/payments/refund",
                                  {"charge_id": args.charge})
        if rc is None:
            return _down()
        if rc != 200:
            print(f"{_ANSI['bad']}HTTP {rc}: {data}{_ANSI['off']}")
            return 1
        print(f"{_ANSI['ok']}{t['pay_refund_ok']}{_ANSI['off']}: "
              f"{data.get('status')} ${data.get('amount_usd')}")
        return 0
    print(f"{_ANSI['bad']}{t['pay_unknown']}: {act}{_ANSI['off']}")
    return 1


def _expires(value: object) -> str:
    """Render an expiry as a date, or say plainly that it is not a date.

    The API reports timestamps as epoch floats, and `1793386638.9044793` on its
    own is a number an operator has to convert by hand to answer the only
    question they have ("how long do I have?"). An unknown value prints as
    `unknown` rather than as a formatted 1970 date, which is what a zero epoch
    would silently become.
    """
    try:
        secs = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if secs <= 0:
        return "unknown"
    return datetime.fromtimestamp(secs).strftime("%Y-%m-%d %H:%M")


def cmd_products(args: argparse.Namespace) -> int:
    """The product catalogue (34.19) — what can be bought, and what is held.

    Read-only and never a purchase path: buying goes through
    `tradraig challenge buy`, which posts to `/payments/product` so the price
    and the entitlement come from the server's catalogue. A console command
    that could name its own price would make the console a second billing
    authority.
    """
    t = I18N[args.lang]
    base = f"http://127.0.0.1:{API_PORT}"
    ok, data = http_json(f"{base}/payments/products")
    if not ok:
        print(f"{_ANSI['bad']}{t['pay_api_down']}{_ANSI['off']}")
        return 1
    print(f"  catalogue ({data.get('actor') or t['ch_not_entitled']}):")
    for p in data.get("catalog", []):
        print(f"    {p['product_id']:<18} ${p['price_usd']:<7} "
              f"{p['duration_days']}d grace={p['grace_days']}d "
              f"entitlement={p['entitlement']} "
              f"trade_permission={p['grants_trade_permission']}")
    held = (data.get("entitlements") or {}).get("entitlements") or []
    if not held:
        print(f"    {t['ch_not_entitled']}: {t['ch_buy_hint']}")
    for e in held:
        print(f"    [{str(e.get('state', '')):<9}] {e.get('product_id')} "
              f"expires={_expires(e.get('expires_at'))}")
    return 0


def cmd_challenge(args: argparse.Namespace) -> int:
    """Challenge account management (34): status via the API, buy via billing."""
    t = I18N[args.lang]
    base = f"http://127.0.0.1:{API_PORT}"
    act = args.action

    def _down() -> int:
        print(f"{_ANSI['bad']}{t['ch_api_down']}{_ANSI['off']}")
        return 1

    if act == "status":
        ok, data = http_json(f"{base}/challenge/status")
        if not ok:
            return _down()
        commercial = data.get("commercial") or {}
        # The verdict lives under commercial.gate, not at the top level:
        # `commercial` also carries the price and the product record, so reading
        # a flat `entitled` here would report "not entitled" on a paid service.
        gate = commercial.get("gate") or {}
        entitled = bool(gate.get("active"))
        mark = t["ch_entitled"] if entitled else t["ch_not_entitled"]
        colour = _ANSI["ok"] if entitled else _ANSI["warn"]
        print(f"  service: {colour}{mark}{_ANSI['off']} "
              f"(${commercial.get('price_usd')}) "
              f"bootstrap={gate.get('bootstrap')}")
        if gate.get("detail"):
            print(f"    {gate['detail']}")
        record = commercial.get("record") or {}
        if record:
            print(f"    state={record.get('state')} "
                  f"expires={_expires(record.get('expires_at'))}")
        if commercial.get("grants_trade_permission") is False:
            print("    trade permission: no (this service protects an account; "
                  "it does not authorise trading)")
        print(f"  managed={data.get('managed')} "
              f"program={data.get('program') or '-'} "
              f"permission={(data.get('decision') or {}).get('permission', '-')}")
        state = data.get("state") or {}
        if state:
            print(f"  state={state.get('status')} "
                  f"counts={state.get('counts')}")
        report = data.get("headroom") or {}
        dims = report.get("dimensions") or {}
        for name in ("daily_loss", "max_drawdown", "profit_target",
                     "trading_days"):
            head = dims.get(name) or {}
            if not head.get("is_known"):
                print(f"  {name:<14} unknown: {head.get('reason', '')}")
            else:
                print(f"  {name:<14} remaining={head.get('remaining')} "
                      f"buffer={head.get('buffer')}")
        blocking = data.get("blocking_reasons") or []
        if blocking:
            print(f"  {_ANSI['warn']}blocking: {', '.join(blocking)}{_ANSI['off']}")
        return 0

    if act == "policy":
        # There is no list-everything route, and inventing one here would mean
        # the console reading the registry directly -- a second authority over
        # the policies that decide whether a trade is allowed. Both branches go
        # through /challenge/policies: the bare call is the registry's own
        # summary, and provider+program is the only way to enumerate versions.
        if args.provider_name or args.program:
            # Program names contain spaces ("Classic 2-Step"), and a raw space
            # in a URL is a 400 that reads as "API down". Everything interpolated
            # into a query string is quoted here for that reason.
            import urllib.parse

            query = urllib.parse.urlencode(
                {"provider": args.provider_name, "program": args.program})
            ok, data = http_json(f"{base}/challenge/policies?{query}")
            if not ok:
                return _down()
            rows = data.get("versions") or []
            if not rows:
                print(f"  {args.provider_name}/{args.program}: {t['ch_no_policy']}")
                return 0
            for p in rows:
                missing = p.get("missing_rules") or []
                print(f"  v{p.get('policy_version')} "
                      f"from={p.get('effective_from')} "
                      f"until={p.get('effective_until')} "
                      f"complete={p.get('is_fully_specified')}")
                if missing:
                    print(f"    {_ANSI['warn']}unverified: "
                          f"{', '.join(missing)}{_ANSI['off']}")
            return 0
        ok, data = http_json(f"{base}/challenge/policies")
        if not ok:
            return _down()
        reg = data.get("registry") or {}
        print(f"  registered: {reg.get('registered')}")
        accounts = data.get("accounts") or []
        print(f"  accounts: {', '.join(accounts) if accounts else '-'}")
        print(f"  {data.get('baseline_persistence', '')}")
        if not accounts:
            print(f"  {t['ch_no_policy']}")
        return 0

    if act == "buy":
        if not args.user:
            print(f"{_ANSI['warn']}{t['ch_no_user']}{_ANSI['off']}")
            return 1
        rc, data = http_post_json(f"{base}/payments/product", {
            "user_id": args.user, "product_id": args.product,
            "provider": getattr(args, "provider", "") or "",
        })
        if rc is None:
            return _down()
        if rc != 200:
            print(f"{_ANSI['bad']}HTTP {rc}: {data}{_ANSI['off']}")
            return 1
        status = str(data.get("status", ""))
        if status == "succeeded":
            print(f"{_ANSI['ok']}{t['ch_buy_ok']}{_ANSI['off']}: "
                  f"{args.product} -> {data.get('entitlement')} "
                  f"trade_permission={data.get('grants_trade_permission')}")
        else:
            # A live provider lands PENDING by design: only a verified webhook
            # activates the service. Saying "activated" here would be a claim
            # the billing system has not made yet.
            print(f"{_ANSI['warn']}{t['ch_buy_pending']}{_ANSI['off']}: "
                  f"{status} {data.get('charge_id')}")
        return 0

    print(f"{_ANSI['bad']}{t['ch_unknown']}: {act}{_ANSI['off']}")
    return 1


def cmd_portfolio(args: argparse.Namespace) -> int:
    """Portfolio intelligence & capital allocation — always via the API."""
    t = I18N[args.lang]
    base = f"http://127.0.0.1:{API_PORT}"
    act = args.action

    def _down() -> int:
        print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
        return 1

    if act == "state":
        ok, data = http_json(f"{base}/portfolio/state")
        if not ok:
            return _down()
        if getattr(args, "json", False):
            print(json.dumps(data, indent=1))
            return 0
        conc = data.get("concentration", {})
        print(f"portfolio: equity={data.get('equity')} "
              f"gross={data.get('gross_exposure')} "
              f"net={data.get('net_exposure')} "
              f"positions={data.get('open_positions')}")
        print(f"  long={data.get('long_exposure')} "
              f"short={data.get('short_exposure')} "
              f"unreal={data.get('unrealized_pnl')} "
              f"realized={data.get('realized_pnl')}")
        print(f"  concentration: top={conc.get('top_symbol')} "
              f"share={conc.get('top_share')}")
        print(f"  by_strategy: {json.dumps(data.get('by_strategy', {}))}")
        print(f"  by_symbol: {json.dumps(data.get('by_symbol', {}))}")
        return 0

    if act == "alloc":
        ok, data = http_json(f"{base}/portfolio/allocation")
        if not ok:
            return _down()
        if getattr(args, "json", False):
            print(json.dumps(data, indent=1))
            return 0
        print(f"institutional default cap: "
              f"{data.get('institutional_default_cap')}")
        caps = data.get("explicit_caps") or {}
        live = data.get("live_gate") or {}
        if not caps:
            print(f"{_ANSI['dim']}no explicit allocation caps set"
                  f"{_ANSI['off']}")
        for sid in sorted(caps):
            d = live.get(sid, {})
            print(f"  {sid:<24} cap={caps[sid]:.2%} "
                  f"used={d.get('used_fraction', 0.0):.2%} "
                  f"ok={d.get('ok')} ({d.get('reason', '')})")
        return 0

    if act == "correlation":
        ok, data = http_json(f"{base}/portfolio/correlation")
        if not ok:
            return _down()
        if getattr(args, "json", False):
            print(json.dumps(data, indent=1))
            return 0
        pairs = data.get("pairs") or []
        if not pairs:
            print(f"{_ANSI['dim']}no co-tracked strategies yet — "
                  f"needs enough ledger history{_ANSI['off']}")
        for p in pairs:
            tag = ("DIVERSIFYING" if p.get("diversifying")
                   else ("CONCENTRATED" if p.get("concentrated") else ""))
            print(f"  {p['a']:<12} ~ {p['b']:<12} "
                  f"r={p['correlation']:<8} n={p['samples']} {tag}")
        insuff = data.get("insufficient_data") or []
        if insuff:
            print(f"{_ANSI['dim']}insufficient data: {', '.join(insuff)}"
                  f"{_ANSI['off']}")
        return 0

    if act == "set":
        rc, data = http_post_json(f"{base}/portfolio/allocation", {
            "strategy_id": args.strategy,
            "cap": args.cap,
            "allow_override": bool(args.allow_override),
        })
        if rc is None:
            return _down()
        if rc != 200:
            print(f"{_ANSI['bad']}HTTP {rc}: {data}{_ANSI['off']}")
            return 1
        print(f"{_ANSI['ok']}allocation set: {data.get('strategy_id')} "
              f"cap={data.get('cap_applied')} "
              f"clamped={data.get('clamped_to_institutional')}{_ANSI['off']}")
        return 0

    if act == "clear":
        rc, data = http_post_json(
            f"{base}/portfolio/allocation/{args.strategy}", {},
            method="DELETE")
        if rc is None:
            return _down()
        if rc != 200:
            print(f"{_ANSI['bad']}HTTP {rc}: {data}{_ANSI['off']}")
            return 1
        print(f"{_ANSI['ok']}allocation cleared: {data.get('strategy_id')} "
              f"removed={data.get('removed')}{_ANSI['off']}")
        return 0

    print(f"{_ANSI['bad']}unknown action: {act}{_ANSI['off']}")
    return 1


def cmd_secrets(args: argparse.Namespace) -> int:
    """Secrets Vault (28.18) — status shows set flags only, NEVER values.

    Values are provided once at enroll/rotate time and never echoed back;
    the vault encrypts at rest and venues/billing read through it. All writes
    go through the API (single governance authority, audited).
    """
    t = I18N[args.lang]
    base = f"http://127.0.0.1:{API_PORT}"
    act = args.action

    def _down() -> int:
        print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
        return 1

    if act == "status":
        ok, data = http_json(f"{base}/secrets/status")
        if not ok:
            return _down()
        if getattr(args, "json", False):
            print(json.dumps(data, indent=1))
            return 0
        print(f"secrets vault: backend={data.get('backend')} "
              f"persistable={data.get('persistable')} "
              f"enrolled={data.get('count')}")
        slots = data.get("slots") or {}
        if not any(slots.values()):
            print(f"{_ANSI['dim']}no secret slots enrolled yet — keys come "
                  f"from env (bootstrap){_ANSI['off']}")
        for slot, isset in slots.items():
            mark = _ANSI["ok"] + "SET" if isset else _ANSI["dim"] + "env"
            print(f"  {slot:<38} {mark}{_ANSI['off']}")
        return 0

    if act == "set":
        if not args.slot or not args.value:
            print(f"{_ANSI['bad']}secrets set requires --slot and --value"
                  f"{_ANSI['off']}")
            return 1
        rc, data = http_post_json(
            f"{base}/secrets/{args.slot}",
            {"value": args.value},
            method="PUT")
        if rc is None:
            return _down()
        if rc != 200:
            print(f"{_ANSI['bad']}HTTP {rc}: {data}{_ANSI['off']}")
            return 1
        print(f"{_ANSI['ok']}secret enrolled: {data.get('slot')} "
              f"(rotated={data.get('rotated')}) — stored encrypted, "
              f"never echoed{_ANSI['off']}")
        return 0

    if act == "delete":
        if not args.slot:
            print(f"{_ANSI['bad']}secrets delete requires --slot{_ANSI['off']}")
            return 1
        rc, data = http_post_json(f"{base}/secrets/{args.slot}", {},
                                  method="DELETE")
        if rc is None:
            return _down()
        if rc != 200:
            print(f"{_ANSI['bad']}HTTP {rc}: {data}{_ANSI['off']}")
            return 1
        print(f"{_ANSI['ok']}secret revoked: {data.get('slot')} "
              f"removed={data.get('removed')} (falls back to env){_ANSI['off']}")
        return 0

    print(f"{_ANSI['bad']}unknown action: {act}{_ANSI['off']}")
    return 1


def cmd_opportunity(args: argparse.Namespace) -> int:
    """Opportunity Engine (Phase B) — surfacing + operator decision (via API).

    An opportunity is a screened, fully-evidenced setup — it is never a
    trade until it passes the institutional screen and, under the
    operator-confirmation gate (TRADERAIG_OPPORTUNITY_GATE=1), an explicit
    operator decision. Approve/reject go through the API, the single
    governance authority (audited).
    """
    t = I18N[args.lang]
    base = f"http://127.0.0.1:{API_PORT}"
    act = args.action

    def _down() -> int:
        print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
        return 1

    if act == "status":
        ok, data = http_json(f"{base}/opportunities/status")
        if not ok:
            return _down()
        if getattr(args, "json", False):
            print(json.dumps(data, indent=1))
            return 0
        counts = data.get("counts") or {}
        print(f"opportunity gate: {data.get('mode')} "
              f"(TRADERAIG_OPPORTUNITY_GATE; 'confirm' waits for operator)")
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"board: {summary or 'empty'}")
        print(f"approved pending execution: {data.get('pending')}")
        return 0

    if act == "list":
        url = f"{base}/opportunities"
        if getattr(args, "status", ""):
            url += f"?status={args.status}"
        ok, data = http_json(url)
        if not ok:
            return _down()
        if getattr(args, "json", False):
            print(json.dumps(data, indent=1))
            return 0
        if not data:
            print(f"{_ANSI['dim']}no opportunities recorded yet{_ANSI['off']}")
            return 0
        for o in data:
            mark = _ANSI["ok"] if o["risk_ok"] else _ANSI["bad"]
            print(f"{o['opportunity_id']} {o['symbol']:<7} {o['direction']:<5} "
                  f"{mark}{o['status']:<9}{_ANSI['off']} score={o['score']:<3} "
                  f"{o['source']:<24} {o['detected_at'][:19]}Z")
            if o["history"]:
                print(f"  {_ANSI['dim']}{o['history'][-1]['status']}: "
                      f"{o['history'][-1]['note']}{_ANSI['off']}")
        return 0

    if act == "show":
        if not args.id:
            print(f"{_ANSI['bad']}opportunity show requires --id{_ANSI['off']}")
            return 1
        ok, data = http_json(f"{base}/opportunities/{args.id}")
        if not ok:
            print(f"{_ANSI['bad']}HTTP/API: {data}{_ANSI['off']}")
            return 1
        print(f"{data['opportunity_id']} {data['symbol']} {data['direction']} "
              f"[{data['status']}]")
        print(f"  source={data['source']} score={data['score']} "
              f"priority={data['priority']}")
        print(f"  entry={data['entry']} sl={data['stop_loss']} "
              f"tp={data['take_profit']} size={data['size']}")
        print(f"  rr={data['risk_reward']} conf={data['confidence']}")
        print(f"  risk_ok={data['risk_ok']} reason={data['risk_reason']}")
        print(f"  allocation_ok={data['allocation_ok']} "
              f"reason={data['allocation_reason']}")
        print(f"  live_eligible={data['live_eligible']} "
              f"({data['live_eligibility_reason']})")
        if data["screen_reasons"]:
            print("  screen_reasons:")
            for r in data["screen_reasons"]:
                print(f"    - {r}")
        if getattr(args, "json", False):
            print(json.dumps(data, indent=1))
            return 0
        ev = data.get("evidence") or {}
        rd = ev.get("risk_decision") or {}
        print("  risk checks:")
        for c in rd.get("checks") or []:
            print(f"    - {c.get('name')}: passed={c.get('passed')} "
                  f"{c.get('detail', '')}")
        print("  history:")
        for h in data["history"]:
            print(f"    {h['ts'][:19]}Z {h['status']}: {h['note']}")
        return 0

    if act in ("approve", "reject"):
        if not args.id:
            print(f"{_ANSI['bad']}opportunity {act} requires --id{_ANSI['off']}")
            return 1
        if act == "approve":
            rc, data = http_post_json(f"{base}/opportunities/{args.id}/approve", {})
        else:
            body = {"reason": args.reason} if args.reason else {"reason": "operator rejected via console"}
            rc, data = http_post_json(f"{base}/opportunities/{args.id}/reject", body)
        if rc is None:
            return _down()
        if rc != 200:
            print(f"{_ANSI['bad']}HTTP {rc}: {data}{_ANSI['off']}")
            return 1
        print(f"{_ANSI['ok']}opportunity {args.id} -> {data.get('status')} "
              f"(execute_pending={data.get('execute_pending')}){_ANSI['off']}")
        print(f"  {_ANSI['dim']}{data['history'][-1]['status']}: "
              f"{data['history'][-1]['note']}{_ANSI['off']}")
        return 0

    print(f"{_ANSI['bad']}unknown action: {act}{_ANSI['off']}")
    return 1


def cmd_events(args: argparse.Namespace) -> int:
    """Tail the live operations event feed (dashboard/copy-engine consumer)."""
    t = I18N[args.lang]
    base = f"http://127.0.0.1:{API_PORT}"
    q = f"?after={int(getattr(args, 'after', 0))}"
    if getattr(args, "topic", ""):
        q += f"&topic={args.topic}"
    ok, data = http_json(f"{base}/ops/events{q}")
    if not ok:
        print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
        return 1
    rows = data.get("events", [])
    if not rows:
        print(f"{_ANSI['dim']}no events since {q}{_ANSI['off']}")
        return 0
    for e in rows:
        payload = e.get("payload", {})
        flat = ",".join(f"{k}={v}" for k, v in payload.items() if k != "request_id")
        print(f"  #{e.get('id'):<4} {float(e.get('at', 0)):.0f} "
              f"{str(e.get('kind', '')):<10} {str(e.get('topic', '')):<8} "
              f"{str(e.get('actor', '')):<12} {flat}")
    print(f"{_ANSI['ok']}{len(rows)} events{_ANSI['off']} — latest #{data.get('latest')}")
    return 0


def cmd_copy(args: argparse.Namespace) -> int:
    """Copy-engine consumer status (mirror of master decisions)."""
    t = I18N[args.lang]
    base = f"http://127.0.0.1:{API_PORT}"
    ok, data = http_json(f"{base}/ops/copy/follower")
    if not ok:
        print(f"{_ANSI['bad']}{t['u_api_down']}{_ANSI['off']}")
        return 1
    pf = data.get("portfolio", {})
    strategies = pf.get("strategies", {})
    overrides = pf.get("overrides", [])
    if getattr(args, "json", False):
        print(json.dumps(data, indent=1, default=str))
        return 0
    print(f"{_ANSI['ok']}copy-engine: {len(strategies)} mirrored, "
          f"{pf.get('decisions_consumed', 0)} decisions consumed{_ANSI['off']}")
    for key, row in sorted(strategies.items()):
        print(f"  {key:<40} {str(row.get('state', '')):<12} by={row.get('actor', '')}")
    for ov in overrides:
        print(f"{_ANSI['warn']}  conflict {ov.get('key')}: "
              f"{ov.get('previous_state')} -> {ov.get('state')}{_ANSI['off']}")
    return 0


# --------------------------------------------------------------------------- #
# M6.4 disaster recovery
# --------------------------------------------------------------------------- #

def cmd_backup(args: argparse.Namespace) -> int:
    """Snapshot durable canonical state (.data / strategy-lab / proofs / dspy)."""
    from pathlib import Path
    from operations.dr import backup

    res = backup(Path(args.out or os.path.join(ROOT, "backups")),
                 root=Path(ROOT), note=getattr(args, "note", ""))
    if args.json:
        print(json.dumps(res, default=str))
        return 0
    t = I18N[args.lang]
    print(f"{_ANSI['ok']}{t['dr_backup_ok']}{_ANSI['off']}")
    print(f"  {res['archive']}")
    print(f"  {res['count']} files, {res['byte_total']} bytes, "
          f"created {res['created_at']}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    from pathlib import Path
    from operations.dr import restore

    res = restore(Path(args.archive), Path(ROOT), force=args.force,
                  dry_run=args.dry_run)
    if args.json:
        print(json.dumps(res, default=str))
        return 0 if res.get("ok") else 1
    t = I18N[args.lang]
    if not res.get("ok"):
        print(f"{_ANSI['bad']}{t['dr_restore_refused']}{_ANSI['off']}: "
              f"{res.get('error', '')}")
        for c in res.get("conflicts", []):
            print(f"  conflict  {c}")
        return 1
    print(f"{_ANSI['ok']}{t['dr_restore_ok']}{_ANSI['off']}")
    print(f"  {res['archive']}")
    print(f"  restored {res['restored_count']} / skipped "
          f"{res['skipped_count']} / conflicts {len(res['conflicts'])}")
    print(f"  {res.get('note', '')}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from pathlib import Path
    from operations.dr import verify

    res = verify(Path(args.archive))
    if args.json:
        print(json.dumps(res, default=str))
        return 0 if res.get("ok") else 1
    if res.get("ok"):
        print(f"{_ANSI['ok']}verify ok{_ANSI['off']}: "
              f"{res['checked']} files, created {res.get('created_at', '')}")
        return 0
    print(f"{_ANSI['bad']}verify FAILED{_ANSI['off']}: "
          f"{res.get('error', 'corrupt archive')}")
    for m in res.get("mismatched", []):
        print(f"  MISMATCH  {m}")
    return 1


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tradraig",
                                description="TraderAIG operator console (IIOS).")
    p.add_argument("--lang", choices=("en", "ar"), default="en")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="layer health screen")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    lg = sub.add_parser("login", help="open a session for the console (28.19)")
    lg.add_argument("--email", default="")
    lg.add_argument("--password", default="")
    lg.set_defaults(fn=cmd_login)

    d = sub.add_parser("doctor", help="self-diagnosis + fixes")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_doctor)

    st = sub.add_parser("start", help="start layers detached")
    st.add_argument("target", choices=("backend", "dash", "ollama", "all"))
    st.set_defaults(fn=cmd_start)

    sp = sub.add_parser("stop", help="stop a layer by port")
    sp.add_argument("target", choices=("backend", "dash", "ollama"))
    sp.set_defaults(fn=cmd_stop)

    t = sub.add_parser("test", help="run the test suite")
    t.add_argument("--fast", action="store_true", help="ai/dspy targeted only")
    t.add_argument("--timeout", type=int, default=600)
    t.set_defaults(fn=cmd_test)

    dsp = sub.add_parser("dspy", help="DSPy/AI layer ops")
    dsp.add_argument("action", choices=("status", "models", "optimize", "proposal"))
    dsp.add_argument("--model")
    dsp.add_argument("--program", default="ict_scalping")
    dsp.add_argument("--trials", type=int, default=6)
    dsp.add_argument("--json", action="store_true")
    dsp.set_defaults(fn=cmd_dspy)

    g = sub.add_parser("gate", help="flip the machine-level DSPy gate (User scope)")
    g.add_argument("state", choices=("on", "off"))
    g.set_defaults(fn=cmd_gate)

    i = sub.add_parser("info", help="versions / models / RAM")
    i.set_defaults(fn=cmd_info)

    b = sub.add_parser("board", help="probe dashboard feeds; per-widget live/static verdict")
    b.add_argument("--json", action="store_true")
    b.set_defaults(fn=cmd_board)

    u = sub.add_parser("user", help="identity ops (via the API — single governance authority)")
    ua = u.add_subparsers(dest="action", required=True)
    uc = ua.add_parser("create", help="create an identity")
    uc.add_argument("--email", required=True)
    uc.add_argument("--display", default="")
    uc.add_argument("--plan", choices=("free", "starter", "pro", "institutional"),
                    default="free")
    uc.set_defaults(fn=cmd_user)
    ul = ua.add_parser("list", help="list identities")
    ul.set_defaults(fn=cmd_user)

    st = sub.add_parser("strategy", help="user strategy intake: describe -> vet -> test -> governed production")
    sta = st.add_subparsers(dest="action", required=True)

    sp_p = sta.add_parser("propose", help="describe a strategy in words; the project vets it immediately")
    sp_p.add_argument("--text", required=True,
                      help="natural-language strategy description")
    sp_p.add_argument("--asset", default="XAUUSD")
    sp_p.add_argument("--family", default="",
                      help="detector hint: ict / fvg / order block / liquidity sweep / bos / wyckoff / pattern")
    sp_p.add_argument("--trigger", default="",
                      choices=("", "zone_touch", "close_confirm", "retest_confirm",
                               "m1_refinement"))
    sp_p.add_argument("--exit", default="",
                      choices=("", "fixed_r", "liquidity_target", "time_stop",
                               "structure_trail"))
    sp_p.add_argument("--min-rr", type=float, default=None)
    sp_p.add_argument("--session", default="",
                      choices=("", "london", "newyork", "asia", "sydney"))
    sp_p.add_argument("--by", default="operator")
    sp_p.set_defaults(fn=cmd_strategy)

    sp_v = sta.add_parser("vet", help="re-run the scrutinizer after revising hints (REVISE loop)")
    sp_v.add_argument("id")
    sp_v.add_argument("--family", default="")
    sp_v.add_argument("--trigger", default="",
                      choices=("", "zone_touch", "close_confirm", "retest_confirm",
                               "m1_refinement"))
    sp_v.add_argument("--exit", default="",
                      choices=("", "fixed_r", "liquidity_target", "time_stop",
                               "structure_trail"))
    sp_v.add_argument("--min-rr", type=float, default=None)
    sp_v.add_argument("--session", default="",
                      choices=("", "london", "newyork", "asia", "sydney"))
    sp_v.set_defaults(fn=cmd_strategy)

    sp_t = sta.add_parser("test", help="run the vetted strategy through the lab pipeline (blocking)")
    sp_t.add_argument("id")
    sp_t.add_argument("--source", default="mt5",
                      choices=("mt5", "csv", "synthetic"))
    sp_t.add_argument("--count", type=int, default=20000)
    sp_t.add_argument("--cost-r", type=float, default=0.0)
    sp_t.add_argument("--timeout", type=int, default=300)
    sp_t.set_defaults(fn=cmd_strategy)

    sp_l = sta.add_parser("list", help="list intake entries")
    sp_l.add_argument("--status", default="",
                      choices=("", "PROPOSED", "VETTED", "REVISE", "REJECTED",
                               "TESTED"))
    sp_l.set_defaults(fn=cmd_strategy)

    sp_s = sta.add_parser("show", help="show one intake entry")
    sp_s.add_argument("id")
    sp_s.set_defaults(fn=cmd_strategy)

    sp_m = sta.add_parser("promote", help="advance a tested strategy up the governed ladder")
    sp_m.add_argument("id")
    sp_m.add_argument("--by", default="operator")
    sp_m.set_defaults(fn=cmd_strategy)

    ex = sub.add_parser("exercise", help="run an in-process demo exercise (populates live veto/learning feeds)")
    ex.add_argument("--seconds", type=float, default=20.0)
    ex.add_argument("--status", action="store_true", help="show last exercise state")
    ex.set_defaults(fn=cmd_exercise)

    ch = sub.add_parser("change", help="Change Governance — audited change-request tracker (via the API)")
    cha = ch.add_subparsers(dest="action", required=True)

    def _ch_common(p):
        p.add_argument("--decided-by", default="operator")
        p.add_argument("--reason", default="")

    cst = cha.add_parser("submit", help="submit a change request (registry never mutates here)")
    cst.add_argument("--kind", required=True, choices=("promote", "quarantine", "config"))
    cst.add_argument("--target", required=True, help="strategy_id (or config key)")
    cst.add_argument("--reason", required=True)
    cst.set_defaults(fn=cmd_change)

    cli = cha.add_parser("list", help="list change requests")
    cli.add_argument("--status", default="", choices=("", "pending", "approved", "denied", "cancelled"))
    cli.set_defaults(fn=cmd_change)

    cap = cha.add_parser("approve", help="approve a pending change (applies promote/quarantine under engine guard)")
    cap.add_argument("id")
    _ch_common(cap)
    cap.set_defaults(fn=cmd_change)

    cde = cha.add_parser("deny", help="deny a pending change")
    cde.add_argument("id")
    _ch_common(cde)
    cde.set_defaults(fn=cmd_change)

    cca = cha.add_parser("cancel", help="cancel your own pending change")
    cca.add_argument("id")
    cca.add_argument("--requested-by", default="operator")
    cca.set_defaults(fn=cmd_change)

    ev = sub.add_parser("events", help="tail the live operations event feed (from the API)")
    ev.add_argument("--after", type=int, default=0)
    ev.add_argument("--topic", default="", choices=("", "registry", "change", "risk", "health", "ops"))
    ev.set_defaults(fn=cmd_events)

    cp = sub.add_parser("copy", help="copy-engine consumer status (mirror of master decisions, via the API)")
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(fn=cmd_copy)

    pay = sub.add_parser("pay", help="Billing & wallet (via the API — single billing authority)")
    pay.add_argument("action", choices=("status", "providers", "charge", "wallet", "refund"),
                     help="status | providers | charge | wallet | refund")
    pay.add_argument("--user", default="", help="user_id (charge/wallet)")
    pay.add_argument("--amount", type=float, default=0.0, help="USD amount (charge)")
    pay.add_argument("--plan", default="",
                     choices=("", "free", "starter", "pro", "institutional"),
                     help="plan to activate on a successful charge")
    pay.add_argument("--provider", default="", choices=("", "sandbox", "stripe", "pi"))
    pay.add_argument("--description", default="")
    pay.add_argument("--charge", default="", help="charge_id (refund)")
    pay.set_defaults(fn=cmd_pay)

    pr = sub.add_parser("products",
                        help="product catalogue + what is held (34.19; read-only)")
    pr.set_defaults(fn=cmd_products)

    cha = sub.add_parser("challenge",
                          help="Challenge account management (34): status / policy / buy")
    cha.add_argument("action", choices=("status", "policy", "buy"),
                      help="status | policy | buy")
    cha.add_argument("--user", default="", help="user_id (buy)")
    cha.add_argument("--product", default="challenge_basic",
                     help="product_id to buy (34.19 catalogue; price is server-side)")
    cha.add_argument("--provider", default="", choices=("", "sandbox", "stripe", "pi"))
    cha.add_argument("--provider-name", default="",
                     help="challenge provider, e.g. FTTrading (policy)")
    cha.add_argument("--program", default="",
                     help="challenge program, e.g. 'Classic 2-Step' (policy)")
    cha.set_defaults(fn=cmd_challenge)

    pf = sub.add_parser("portfolio", help="Portfolio intelligence & capital allocation (via the API)")
    pf.add_argument("action", choices=("state", "alloc", "correlation", "set", "clear"),
                    help="state | alloc | correlation | set | clear")
    pf.add_argument("--strategy", default="", help="strategy_id (set/clear)")
    pf.add_argument("--cap", type=float, default=0.0, help="allocation cap, fraction of equity (set)")
    pf.add_argument("--allow-override", action="store_true",
                    help="allow widening beyond the institutional default (audited)")
    pf.add_argument("--json", action="store_true")
    pf.set_defaults(fn=cmd_portfolio)

    sv = sub.add_parser("secrets", help="Secrets Vault (28.18): status shows set flags only, never values")
    sv.add_argument("action", choices=("status", "set", "delete"),
                    help="status | set | delete")
    sv.add_argument("--slot", default="", help="canonical slot (set/delete), e.g. cex.okx.demo_api_secret")
    sv.add_argument("--value", default="", help="secret value to enroll/rotate (set; never echoed)")
    sv.add_argument("--json", action="store_true")
    sv.set_defaults(fn=cmd_secrets)

    op = sub.add_parser("opportunity", help="Opportunity Engine (Phase B): screened setups — surfacing + operator decision (via API)")
    op.add_argument("action", choices=("status", "list", "show", "approve", "reject"),
                    help="status | list | show | approve | reject")
    op.add_argument("--id", default="", help="opportunity_id (show/approve/reject)")
    op.add_argument("--status", default="", help="filter list by status (comma-separated)")
    op.add_argument("--reason", default="", help="rejection reason (reject)")
    op.add_argument("--json", action="store_true")
    op.set_defaults(fn=cmd_opportunity)

    bk = sub.add_parser("backup", help="snapshot durable canonical state to a ZIP (M6.4)")
    bk.add_argument("--out", default=None, help="destination dir (default <root>/backups)")
    bk.add_argument("--note", default="")
    bk.add_argument("--json", action="store_true")
    bk.set_defaults(fn=cmd_backup)

    rs = sub.add_parser("restore", help="restore a backup ZIP (integrity-checked; non-destructive unless --force)")
    rs.add_argument("archive", help="path to a tradraig-backup-*.zip")
    rs.add_argument("--force", action="store_true", help="overwrite differing files")
    rs.add_argument("--dry-run", action="store_true", help="list writes without touching disk")
    rs.add_argument("--json", action="store_true")
    rs.set_defaults(fn=cmd_restore)

    vf = sub.add_parser("verify", help="integrity-check a backup ZIP against its manifest")
    vf.add_argument("archive", help="path to a tradraig-backup-*.zip")
    vf.add_argument("--json", action="store_true")
    vf.set_defaults(fn=cmd_verify)
    return p


def main() -> int:
    _try_reconfigure_stdout()
    args = _parser().parse_args()
    try:
        return int(args.fn(args) or 0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
