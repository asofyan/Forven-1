# Forven - Agent Instructions

## Project Overview

Forven is a local-first algorithmic trading operations framework. It acts as an autonomous workspace for quantitative trading: strategy creation, backtesting, deployment, and risk management.

- **Backend**: Python 3.11+ / FastAPI - serves on `http://127.0.0.1:8003`
- **Frontend**: SvelteKit 2 (Svelte 5) + TailwindCSS + Vite - serves on `http://127.0.0.1:5173`
- **Database**: SQLite via `forven/db.py`
- **Backtesting**: Built-in bar-by-bar engine with vectorized signal generation
- **Vector Store**: ChromaDB
- **Exchange**: CCXT / Hyperliquid integration under `forven/exchange/`

---

## Repository Layout

```text
forven/                    # Python backend package
  api.py                   # FastAPI app, lifespan, router registration
  api_core.py              # Shared startup, compatibility, and legacy helpers
  control_plane/           # Operator-facing control-plane logic
  api_domains/             # API-facing domain modules and compatibility helpers
  routers/                 # FastAPI routers (one file per domain)
    agents.py              #   /api/agents
    analytics.py           #   /api/dashboard/*, /api/stats, scanner analytics
    approvals.py           #   /api/approvals
    auth.py                #   /api/auth/providers/*
    backtesting.py         #   /api/backtesting/*
    data.py                #   /api/data/* and dataset routes
    jobs.py                #   /api/jobs
    legacy.py              #   /api/forven/* compatibility routes
    lifecycle.py           #   /api/lifecycle/*
    memory.py              #   /api/memory/*
    notifications.py       #   /api/notifications/*
    ops.py                 #   /api/system/*, /api/logs, scheduler, resets
    paper.py               #   /api/paper/*
    quant_factory.py       #   /api/quant-factory
    robustness.py          #   /api/robustness/*
    simulation.py          #   /api/simulation/*
    status.py              #   /, /api/health, dashboard and status routes
    strategies.py          #   /api/strategies and results routes
    system.py              #   /api/settings/*, brain chat, system helpers
    tasks.py               #   /api/tasks and pipeline task audit routes
    trading.py             #   /api/trades/*
    verdict.py             #   /verdict/*
    webhooks.py            #   /api/webhooks/*
    websockets.py          #   /api/ws/live and /ws/live
  strategies/
    base.py                # BaseStrategy interface - all strategies extend this
    backtest.py            # Backtest engine, run_backtest()
    optimizer.py           # Grid search and optimization helpers
    fitness.py             # Fitness scoring functions
    registry.py            # Strategy discovery and loading
    sentiment.py           # Sentiment-based signal helpers
    builtin/               # Shipped strategies
    custom/                # User-created strategies (gitignored)
  cli.py                   # Click CLI (`python -m forven ...`)
  config.py                # Global configuration loader
  data.py                  # Market data download and ingestion
  db.py                    # SQLite schema and session helpers
  policy.py                # Pipeline stages and gate criteria
  scanner.py               # Market screener / scanner logic
  scheduler.py             # Cron-style task scheduling
  simulation.py            # Core simulation engine

frontend/                  # SvelteKit frontend
  src/
    routes/
      +page.svelte         #   /
      agents/              #   /agents
      ai-dropzone/         #   /ai-dropzone
      approval/            #   /approval
      data/                #   /data
      lab/                 #   /lab
        strategy/[id]/     #   /lab/strategy/:id
      memory/              #   /memory
      ops/                 #   /ops
      risk/                #   /risk
      runs/                #   /runs
      settings/            #   /settings
      tasks/               #   /tasks
      trades/              #   /trades
    lib/
      api/                 # Typed API client modules
      stores/              # Svelte writable stores
      components/          # Reusable Svelte components

tests/                     # pytest suite
docs/                      # project documentation
templates/workspace/       # agent workspace file templates
```

---

## Key Conventions

### Backend (Python)

- **Import style**: Always use absolute imports - `from forven.module import X`, never relative.
- **Router pattern**: Keep FastAPI endpoints thin and delegate business logic to focused modules.
- **Pipeline stages**: `researching -> backtesting -> paper -> deployed -> retired` (see `forven/policy.py`).
- **Type hints**: All function signatures should have type hints.
- **Linter**: Ruff.
- **Tests**: pytest under `tests/`.
- **Async**: FastAPI endpoints are async where appropriate; heavy compute can be offloaded.

### Frontend (SvelteKit / TypeScript)

- **API calls**: Route backend communication through `frontend/src/lib/api/`.
- **State**: Shared stores live in `frontend/src/lib/stores/`.
- **Styling**: TailwindCSS utility classes.
- **Components**: Reusable UI belongs in `frontend/src/lib/components/`.

---

## Running the Project

```powershell
# Full stack (recommended on Windows)
powershell -ExecutionPolicy Bypass -File .\start_all.ps1

# Full stack (macOS/Linux)
bash start_all.sh

# Backend only
python -m uvicorn --app-dir . forven.api:app --host 127.0.0.1 --port 8003 --reload

# Frontend only
cd frontend
npm run dev

# CLI
python -m forven --help

# Tests
python -m pytest tests -q

# Linting
python -m ruff check forven tests
```

Important:

- `python -m forven` launches the CLI, not the API server.
- `start_all.ps1` is the most complete bootstrap path on Windows and can auto-create `.venv` plus install missing dependencies.

---

## Operational Setup (this machine)

Backend berjalan sebagai **systemd service** — jangan di-start manual via CLI:

```
# Service files
/etc/systemd/system/forven-backend.service   # port 8004 (BUKAN 8003)
/etc/systemd/system/forven-frontend.service

# Management
sudo systemctl status forven-backend
sudo systemctl restart forven-backend
sudo journalctl -u forven-backend -n 50 --no-pager   # logs
```

### Environment & Auth

```
# .env file
/home/hms/forven/.env

# API keys (untuk forven.agent)
FORVEN_API_URL=http://127.0.0.1:8004
FORVEN_API_KEY=92ec5b339a6a980a8c3d6dc31b237ac4e9572a520921ce454fb5bf049839d7c0
FORVEN_OPERATOR_KEY=295dc8d02f34f301b6456ae19f4b5b02e8bddc815b124729c020d57dba573566

# Database
/home/hms/.forven/forven.db  (SQLite)
```

### Invoke forven.agent (dengan auth)

```bash
cd /home/hms/forven
FORVEN_API_URL=http://127.0.0.1:8004 \
  FORVEN_API_KEY=92ec5b339a6a980a8c3d6dc31b237ac4e9572a520921ce454fb5bf049839d7c0 \
  FORVEN_OPERATOR_KEY=295dc8d02f34f301b6456ae19f4b5b02e8bddc815b124729c020d57dba573566 \
  .venv/bin/python -m forven.agent <command>
```

Atau set env vars dulu:
```bash
export FORVEN_API_URL=http://127.0.0.1:8004
export FORVEN_API_KEY=92ec5b339a6a980a8c3d6dc31b237ac4e9572a520921ce454fb5bf049839d7c0
export FORVEN_OPERATOR_KEY=295dc8d02f34f301b6456ae19f4b5b02e8bddc815b124729c020d57dba573566
export PATH=/home/hms/forven/.venv/bin:$PATH
```

---

## Strategy Development — Practical Knowledge

### Available Datasets (BTC/USDT)

| ID | Timeframe | Bars | Period |
|----|-----------|------|--------|
| dataset-0 | 15m | 70,079 | 2024-07-06 → 2026-07-06 |
| dataset-2 | 1h | 17,519 | 2024-07-06 → 2026-07-06 |
| dataset-3 | 4h | 4,379 | 2024-07-06 → 2026-07-06 |

Juga ETH/USDT dan SOL/USDT di timeframe yg sama.

### Cara bikin strategi yang benar

1. **Extend `DonchianStrategy`** (builtin) atau `BaseStrategy` — pastikan punya BOTH `generate_signal()` dan `generate_signals()`
2. **Vectorized path wajib** — `generate_signals` return `(entry_series: pd.Series, exit_series: pd.Series)`
3. **Lookahead-safe** — gunakan `.shift(1)` pada channel/indicator (lihat `forven/strategies/builtin/donchian.py` `donchian_bands()`)
4. **Simpan di** `forven/strategies/custom/`
5. **TYPE_NAME unik** setiap kali registrasi (tidak bisa re-register type yg sama)
6. **Register** → `forven.agent register --file /abs/path/strat.py`
7. **Backtest** → `forven.agent backtest --strategy SXXXXX --dataset BTC/USDT-1h --compact`

---

## Strategy Creation Recipes (AI Agent Quick Reference)

Gunakan section ini untuk membuat, backtest, dan mendaftarkan strategi ke pipeline tanpa perlu eksplorasi ulang.

### Strategy File Template (lengkap)

```python
# forven/strategies/custom/<nama_file>.py
"""Deskripsi singkat strategi."""
import pandas as pd
from forven.strategies.base import BaseStrategy, Signal

TYPE_NAME = "nama_unik_snake_case"  # ← wajib unik global, ganti tiap iterasi

class NamaStrategi(BaseStrategy):

    @property
    def name(self) -> str:
        return f"Nama Human-Readable ({self.asset})"

    @property
    def asset(self) -> str:
        return self.params.get("_asset", "BTC")

    @property
    def strategy_type(self) -> str:
        return TYPE_NAME

    @property
    def default_params(self) -> dict:
        return {
            "period": 20,
            "threshold": 0.5,
            "leverage": 3.0,
        }

    @property
    def compatible_regimes(self) -> set[str]:
        return {"TREND_UP", "TREND_DOWN", "RANGE_BOUND"}

    # ── Per-bar logic (single step) ──
    # 🔴 WAJIB: implementasi nyata, BUKAN stub `Signal.from_condition(False, ...)`.
    # Scanner live panggil ini — stub = 0 trade di paper selamanya.
    # Gunakan helper/indikator yg sama dgn generate_signals(), evaluasi bar terakhir.
    def generate_signal(self, df: pd.DataFrame) -> Signal:
        period = int(self.params.get("period", 20))
        if len(df) < period + 2:
            return Signal(entry_signal=False, exit_signal=False, price=0.0)

        # ... logika entry/exit per bar ...
        curr_close = float(df["close"].iloc[-1])

        return Signal(
            entry_signal=False,   # True jika entry
            exit_signal=False,    # True jika exit
            price=round(curr_close, 4),
            direction="long",
            confidence=0.0,
        )

    # ── Vectorized logic (wajib untuk performa) ──
    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        period = int(self.params.get("period", 20))
        close = df["close"]

        # CONTOH: breakout di atas rolling high sebelumnya (lookahead-safe)
        upper = df["high"].rolling(period).max().shift(1)  # ← .shift(1) wajib
        entry = close > upper
        exit_ = pd.Series(False, index=df.index)

        return entry.fillna(False), exit_.fillna(False)

    def parameter_space(self) -> dict:
        return {"period": (10, 50, 5), "threshold": (0.1, 0.9, 0.2)}


# ── Module exports (wajib) ──
STRATEGY_CLASS = NamaStrategi
```

### Aturan Kritis (harus dipatuhi)

| # | Aturan | Konsekuensi jika dilanggar |
|---|--------|---------------------------|
| 1 | `TYPE_NAME` snake_case, unik global | Re-register type yang sudah ada → ditolak |
| 2 | `.shift(1)` pada semua indikator/rolling window | Lookahead → strategy di-reject di registration |
| 3 | Implementasi BOTH `generate_signal()` DAN `generate_signals()` | Tanpa vectorized → O(N²), bisa timeout |
| 3b | 🔴 **`generate_signal()` HARUS implementasi nyata, BUKAN stub `Signal.from_condition(False, ...)`**. Scanner live panggil `generate_signal()` per-bar; stub = 0 trade selamanya di paper. Lihat section "PITFALL" di bawah. | Chart muncul panah buy tapi tidak ada eksekusi trade — 0 trade selamanya |
| 4 | Return `(pd.Series bool, pd.Series bool)` dari `generate_signals()` | Tipe salah → error runtime |
| 5 | Jangan taruh `stop_loss_pct` / `risk_pct` di `default_params` | Engine yang handle risk management |
| 6 | Set `compatible_regimes` (minimal 1) | Kosong → engine force-exit tiap posisi |
| 7 | File di `forven/strategies/custom/` | Registry hanya scan builtin/ dan custom/ |
| 8 | Export `TYPE_NAME` dan `STRATEGY_CLASS` di level module | Registry tidak bisa load tanpa ini |
| 9 | Banned imports: `os`, `subprocess`, `socket`, `eval`, library `ta` | AST security scan reject |
| 10 | Ganti `TYPE_NAME` setiap ubah `default_params` | Re-register tanpa rename tidak refresh snapshot |

### Recipe A: CLI (forven.agent)

```bash
# Setup env
export FORVEN_API_URL=http://127.0.0.1:8004
export FORVEN_API_KEY=92ec5b339a6a980a8c3d6dc31b237ac4e9572a520921ce454fb5bf049839d7c0
export FORVEN_OPERATOR_KEY=295dc8d02f34f301b6456ae19f4b5b02e8bddc815b124729c020d57dba573566
export PATH=/home/hms/forven/.venv/bin:$PATH

# 1. Register
python -m forven.agent register --file /home/hms/forven/forven/strategies/custom/nama_file.py
# Output: {"strategy_id": "S02550", ...}

# 2. Backtest (compact = ringkasan, tanpa compact = full result)
SID="S02550"
python -m forven.agent backtest --strategy $SID --dataset BTC/USDT-1h --compact

# 3. Cek gate readiness
python -m forven.agent gate-report $SID

# 4. Promote ke gauntlet (jika quick_screen pass)
python -m forven.agent promote --strategy $SID --to gauntlet --from quick_screen

# 5. One-shot pipeline (register → backtest → screen → promote otomatis)
python -m forven.agent enqueue --file /home/hms/forven/forven/strategies/custom/nama_file.py --dataset BTC/USDT-1h

# 6. Tunggu sampai paper (background worker yang proses)
python -m forven.agent wait-paper --strategies $SID --timeout 1800

# Utils
python -m forven.agent list --status paper          # cek strategi di paper
python -m forven.agent list --status gauntlet       # cek strategi di gauntlet
python -m forven.agent strategy $SID                # detail satu strategi
python -m forven.agent status $SID                  # status lifecycle
python -m forven.agent context --out /tmp/ctx.json  # datasets, families, template
```

### Recipe B: ForvenAgentClient (Python)

```python
from forven.agent import ForvenAgentClient

fc = ForvenAgentClient()  # baca FORVEN_API_URL, FORVEN_API_KEY dari env

# Register → dapat strategy_id
reg = fc.register_file("/home/hms/forven/forven/strategies/custom/nama_file.py")
sid = reg["strategy_id"]  # "S02550"

# Backtest
result = fc.run_backtest(sid, "BTC/USDT-1h", compact=True)
# result = {"in_sample": {...}, "out_of_sample": {...}}

# Optional: optimasi parameter
opt = fc.run_optimization(sid, "BTC/USDT-1h", n_trials=30)

# Quick screen check
screen = ForvenAgentClient.quick_screen(result)
if screen["pass"]:
    fc.promote(sid, "gauntlet", from_status="quick_screen")

# One-shot full pipeline
verdict = fc.enqueue_candidate("/home/hms/forven/forven/strategies/custom/nama_file.py", "BTC/USDT-1h")
if verdict.get("enqueued"):
    final = fc.wait_for_paper([sid], timeout=2400)

# Session-based (group strategies)
session = fc.create_session(label="hunt-btc-meanrev", objective="BTC mean reversion hunting")
fc.register_file("/path/to/strat.py", session_id=session["id"])
```

### Recipe C: REST API (curl)

```bash
BASE="http://127.0.0.1:8004"

# Register
curl -sS -X POST "$BASE/api/strategies/intake/register-file" \
  -H "Content-Type: application/json" \
  -H "x-api-key: 92ec5b339a6a980a8c3d6dc31b237ac4e9572a520921ce454fb5bf049839d7c0" \
  -d '{"file_path": "/home/hms/forven/forven/strategies/custom/nama_file.py"}'

# Backtest
curl -sS -X POST "$BASE/api/backtesting/run" \
  -H "Content-Type: application/json" \
  -d '{"strategy_id": "S02550", "dataset_id": "BTC/USDT-1h"}'

# Cek hasil backtest
curl -sS "$BASE/api/results?strategy=S02550&limit=5"

# Cek readiness untuk promotion
curl -sS "$BASE/api/lifecycle/strategies/S02550/readiness"

# Promote
curl -sS -X POST "$BASE/api/strategies/S02550/promote" \
  -H "Content-Type: application/json" \
  -d '{"to_status": "gauntlet", "from_status": "quick_screen"}'

# List strategi by status
curl -sS "$BASE/api/strategies?status=paper"

# Health
curl -sS "$BASE/api/health"
```

### Lifecycle Pipeline

```
register_file() ──→ quick_screen ──→ gauntlet ──→ paper ──→ deployed
                        │                              │
                    (backtest +                  (12-step Advancer:
                     pre-screen)                  cost_stress, deflated Sharpe,
                                                  param jitter, walk-forward,
                                                  8 other gates)
```

**Gate thresholds (quick_screen):**

| Metric | Minimum | Target |
|--------|---------|--------|
| Profit Factor | ≥ 1.05 | ≥ 1.3 |
| Sharpe | [0, 5] | ~1.7 OOS |
| Max Drawdown | < 30% | — |
| IS Trades | ≥ 20 | — |
| OOS Trades | ≥ 15 | — |
| Robustness | ≥ 50 | — |

### 🔴 PITFALL: `generate_signal()` Stub — Penyebab #1 Custom Strategy 0 Trade di Paper

**Ini adalah bug paling mematikan dan paling sulit dideteksi.**

Live scanner memanggil `generate_signal()` (per-bar scalar), BUKAN `generate_signals()` (vectorized).
Chart frontend menggunakan `generate_signals()` via kernel replay — jadi panah buy TETAP MUNCUL di chart
meskipun live execution tidak pernah menyentuh kode entry.

**Gejala:**
- ✅ Chart frontend muncul panah entry/exit (dari `generate_signals()`)
- ✅ Backtest menghasilkan trade (dari `generate_signals()`)
- ❌ Paper trading TIDAK PERNAH entry — 0 trade selamanya
- ❌ Scanner log: `entry=-` setiap siklus
- ❌ `scanner_signal_results`: `matched=0, block_reason=no_signal`

**Penyebab — STUB:**
```python
# ❌ JANGAN PERNAH TULIS INI! Live execution tidak akan pernah entry
def generate_signal(self, df: pd.DataFrame) -> Signal:
    return Signal.from_condition(False, df=df, direction="long", confidence=0.0)
```

**Perbaikan — implementasi nyata:**
```python
# ✅ Gunakan helper yg sama dgn generate_signals(), evaluasi bar terakhir
def generate_signal(self, df: pd.DataFrame) -> Signal:
    p = self.params if getattr(self, 'params', None) else self.default_params
    period = int(p.get("period", 20))
    if len(df) < period + 2:
        return Signal(entry_signal=False, exit_signal=False, price=0.0)

    # ... hitung indikator (EMA, MACD, RSI, Bollinger, dsb) ...
    # ... evaluasi kondisi entry/exit pada bar terakhir ...
    curr_close = float(df["close"].iloc[-1])
    return Signal(
        entry_signal=entry_condition_met,
        exit_signal=exit_condition_met,
        price=round(curr_close, 4),
        direction="long",
        confidence=0.8 if entry_condition_met else 0.0,
    )
```

**Cara deteksi:** 
```bash
grep -l "Signal.from_condition(False" forven/strategies/custom/*.py
# Setiap file yang muncul = BUG, harus diperbaiki sebelum register
```

### Signal Dataclass Reference

```python
from dataclasses import dataclass, field

@dataclass
class Signal:
    entry_signal: bool = False
    exit_signal: bool = False
    price: float = 0.0
    direction: str = "long"        # "long" | "short"
    confidence: float = 0.0
    indicators: dict = field(default_factory=dict)
    regime_tag: str | None = None
```

### Gate Requirements (quick_screen)

| Metric | Bar | Target |
|--------|-----|--------|
| Total Trades | ≥ 35 total (IS 20 + OOS 15) | — |
| PF | ≥ 1.05 | aim 1.3+ |
| Sharpe | [0, 5] | — |
| MaxDD | < 30% | — |
| Robustness | ≥ 50 | — |

### Lessons learned dari H00293 (BTC Donchian)

- **Semua 47+ BTC donchian strategies archived/rejected** — zero paper
- **Hanya SOL donchian yang survive** (S00718, S00828, S00950 di paper)
- BTC 1h/4h microstructure: Donchian breakout terlalu jarang, ADX filter bikin makin jarang
- Donchian period 20 lebih baik dari 40 (lebih banyak sinyal)
- SOL punya karakteristik high-chop, slow-trending yang cocok untuk Donchian

### Pre-built families yang tersedia

```
dictionary_family = {
  bb_fade, bb_squeeze, bollinger, donchian, ema_cross, funding,
  inside_bar, keltner, macd, orb, parabolic_sar, regime_filtered,
  rsi_momentum, stochastic, supertrend, vwap_pullback, williams_r
}
```

Parameter kanonikal per family bisa dicek via:
```
forven.agent context --out /tmp/ctx.json
# lalu lihat canonical_params
```

---

## Hypothesis System

- Status: `proposed` → `researching` → `proven`/`disproven`
- Tiap hypothesis punya **spawn limit** untuk child strategies (H00293 sudah penuh)
- Gunakan hypothesis_id yg masih punya quota
- Cek hypothesis:
  ```bash
  sqlite3 /home/hms/.forven/forven.db "SELECT id, display_id, title, status FROM hypotheses ORDER BY created_at DESC"
  ```

---

## Perintah forven.agent lengkap

```bash
# Cek
health                          # status backend
context --out .tmp/ctx.json     # context lengkap
strategy SXXXXX                 # detail strategi
gate-report SXXXXX              # status gate
list --status paper             # daftar strategi berdasarkan status
result <result_id>              # full backtest result

# Lifecycle
register --file /abs/path/strat.py
backtest --strategy SXXXXX --dataset BTC/USDT-1h --compact
optimize --strategy SXXXXX --dataset BTC/USDT-1h --n-trials 30
promote --strategy SXXXXX --to gauntlet --from quick_screen
enqueue --file /abs/path/strat.py --dataset BTC/USDT-1h

# Polling
wait-paper --strategies SXXXXX,SYYYYY --timeout 1800
status SXXXXX,SYYYYY
```

---

## Important Patterns To Follow

1. **Adding a new backend endpoint**
   - Create or edit a router in `forven/routers/`
   - Add business logic in a focused backend module
   - Register the router in `forven/api.py` if it is new
   - Add a corresponding API wrapper in `frontend/src/lib/api/`

2. **Adding a new strategy**
   - Extend `BaseStrategy` from `forven/strategies/base.py`
   - Place it in `forven/strategies/builtin/` or `forven/strategies/custom/`
   - Register it through `forven/strategies/registry.py`

3. **Adding a frontend route**
   - Create `frontend/src/routes/<name>/`
   - Add `+page.svelte` and optional loader files
   - Add typed API client functions if the route needs new backend data

---

## Do NOT

- Commit `.env`, `*.db`, auth tokens, or files in `.forven_home/`
- Modify `forven/exchange/` without explicit instruction
- Use relative imports in backend code
- Put business logic directly in router files
- Use raw `fetch()` in Svelte components when a typed API client belongs in `frontend/src/lib/api/`
- Install new Python dependencies without updating `pyproject.toml`

---

## Driving Forven programmatically (no MCP) — `forven.agent`

The Forven MCP server is only a thin **stdio wrapper** over the backend REST API
on `:8003` (the same API the frontend uses). When you can't use MCP — Codex, the
Tauri app, a sidecar, CI, or when MCP drops — use the **zero-dependency HTTP
harness** instead. It does everything MCP does.

**Shell (Claude Code / Codex):** every command prints JSON to stdout.
```bash
python -m forven.agent health
python -m forven.agent context --out .tmp/ctx.json     # datasets, template, param families (large)
python -m forven.agent list --status paper
python -m forven.agent gate-report S02545              # why a strategy is/isn't promotable
# write a strategy .py to forven/strategies/custom/, then one-shot the genuine pipeline:
python -m forven.agent enqueue --file /abs/path/strat.py --dataset BTC/USDT-1h
python -m forven.agent wait-paper --strategies S02545,S02604 --timeout 1800
```
Also installed as the `forven-agent` console script. Full command list + the gate
reality (quick_screen / cost_stress / deflated-Sharpe) are in `forven/agent/README.md`.

**Python (sidecars/embedding):**
```python
from forven.agent import ForvenAgentClient
fc = ForvenAgentClient()                       # http://127.0.0.1:8003, env-overridable
verdict = fc.enqueue_candidate("/abs/strat.py", "BTC/USDT-1h")   # register→backtest→screen→promote (force=false)
```

**In-app / Tauri / browser (TypeScript):** use `frontend/src/lib/api/agent.ts`
(`ForvenAgent`), which reuses the app's `fetchApi` (auth + base discovery):
```ts
import ForvenAgent from '$lib/api/agent';
const v = await ForvenAgent.enqueueCandidate('/abs/strat.py', 'BTC/USDT-1h');
```

Rules: never pass `force=true` to skip a gate; set `compatible_regimes =
["trending","volatile","range_bound"]` on custom strategies; no `stop_loss_pct`
in `default_params`. Auth (only if `:8003` is exposed beyond localhost): set
`FORVEN_API_KEY` / `FORVEN_OPERATOR_KEY`.
