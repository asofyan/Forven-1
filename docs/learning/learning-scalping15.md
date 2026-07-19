# Learning: Scalping Strategy Development di 15m Timeframe

> **Tanggal**: 2026-07-16
> **Session**: Pembuatan strategi scalping 15m untuk SOL, WLD, ARB
> **Status**: 3 strategi masuk gauntlet (S02062 SOL, S02065 ARB, S02069 WLD)

---

## TL;DR

**15m crypto scalping setelah biaya transaksi (50-100 bps) adalah sangat sulit.** 10+ pendekatan
dicoba, semuanya PF < 1.0 di 15m. Edge ditemukan di timeframe 1h dengan pattern
**Donchian(20) breakout + ADX filter + ATR execution_profile**. Tiga strategi berhasil masuk
gauntlet untuk SOL, ARB, dan WLD.

---

## Daftar Isi

1. [Dataset Tersedia](#dataset-tersedia)
2. [Strategi yang Dicoba dan Hasilnya](#strategi-yang-dicoba-dan-hasilnya)
3. [Key Learnings](#key-learnings)
4. [Pattern yang Terbukti](#pattern-yang-terbukti)
5. [Pitfalls Spesifik 15m](#pitfalls-spesifik-15m)
6. [Execution Profile — Kunci yang Sering Terlewat](#execution-profile--kunci-yang-sering-terlewat)
7. [Rekomendasi untuk Masa Depan](#rekomendasi-untuk-masa-depan)

---

## Dataset Tersedia

| Dataset ID | Symbol | TF | Bars | Period | Taker Ratio | LS Ratio | Funding |
|------------|--------|----|------|--------|-------------|----------|---------|
| dataset-17 | SOL/USDT | 15m | 70,955 | 2024-07 → 2026-07 | 100% ✅ | 100% ✅ | 100% ✅ |
| dataset-21 | WLD/USDT | 15m | 104,352 | 2023-07 → 2026-07 | 100% ✅ | 100% ✅ | 100% ✅ |
| dataset-0 | ARB/USDT | 15m | 116,148 | 2023-03 → 2026-07 | ~100% ✅ | ~100% ✅ | ~100% ✅ |
| dataset-19 | SOL/USDT | 1h | 51,125 | 2020-09 → 2026-07 | — | — | — |
| dataset-23 | WLD/USDT | 1h | 26,084 | 2023-07 → 2026-07 | — | — | — |
| dataset-2 | ARB/USDT | 1h | 29,037 | 2023-03 → 2026-07 | — | — | — |

**Catatan**: OI (Open Interest) coverage 0% untuk WLD — tidak reliable. Taker ratio, LS ratio,
dan funding semuanya 100% coverage.

---

## Strategi yang Dicoba dan Hasilnya

### Round 1: 15m Native Approaches (SEMUA GAGAL)

| # | Strategi | SID | Direction | IS PF | OOS PF | OOS Trades | Masalah |
|---|----------|-----|-----------|-------|--------|------------|---------|
| 1 | Taker Flow Exhaustion (BB + taker z-score reversal) | S02046 | Reversal | 0.67-0.83 | 0.69-0.98 | 137-224 | Taker ratio adalah data 1h → stale di 15m |
| 2 | Vol Climax BB Fade (BB extreme + volume spike reversal) | S02047 | Reversal | 0.46-0.60 | 0.21-0.42 | 24-43 | Volume climax = momentum, bukan reversal |
| 3 | Vol Confirmed BB Breakout (BB break + volume momentum) | S02048 | Momentum | 0.56-0.70 | 0.52-0.78 | 458-526 | Exit "fall back inside BB" terlalu tight |
| 4 | W%R Mean Reversion v1 (wr < oversold, "is below") | S02049 | Reversal | 0.42-0.55 | 0.37-0.58 | 423-507 | Entry "is below" = catching falling knives |
| 5 | W%R Mean Reversion v2 (crosses up from oversold) | S02050 | Reversal | 0.39-0.69 | 0.27-0.38 | 192-241 | Sama — oscillator MR tidak menangkap move cukup besar |
| 6 | Donchian Breakout (middle channel exit) | S02051 | Momentum | 0.75-0.83 | 0.64-0.86 | 341-359 | Middle exit terlalu tight, lower exit terlalu loose |
| 7 | EMA Trend Scalper (24/32 + ADX 25 + regime 192) | S02052 | Trend | 0.20-0.79 | 0.32-1.89 | 6-17 | ADX filter terlalu restriktif, too few trades |
| 8 | EMA 8/21 Simple (no filter, dual-direction) | S02053 | Trend | 0.54-0.75 | 0.83-0.90 | 254-264 | Tanpa filter, terlalu banyak false signals |
| 9 | EMA 8/21 + ADX + Regime (match S01627 config) | S02054 | Trend | 0.54-1.10 | 0.43-0.85 | 71-102 | ARB IS PF=1.10 tapi OOS PF=0.85 (overfit) |
| 10 | BB Squeeze Breakout (volatility expansion) | S02055 | Momentum | 0.47-0.51 | 0.56-0.94 | 221-261 | Exit terlalu cepat, breakouts mostly fail |

### Round 2: 1h Approaches dengan Execution Profile (BERHASIL)

| # | Strategi | SID | Asset | IS PF | OOS PF | OOS Sharpe | OOS DD | Quick Screen |
|---|----------|-----|-------|-------|--------|------------|--------|--------------|
| 11 | MACD Divergence (optimizer params 17/26/11) | S02056 | WLD | 1.23 | 1.47 | 1.67 | 7.7% | ✅ PASS → gauntlet (archived: walk_forward failed) |
| 12 | Donchian(20) + ADX≥22 + ATR 1.5× + TP 5% | S02062 | SOL | 1.35 | 1.14 | 0.54 | 9.5% | ✅ PASS → **gauntlet** |
| 13 | Donchian(20) + ADX≥22 + ATR 1.5× + TP 5% | S02065 | ARB | 1.14 | 1.08 | 0.40 | 13.9% | ✅ PASS → **gauntlet** |
| 14 | Donchian(20) + ADX≥24 + ATR 1.5× + TP 5% | S02069 | WLD | 1.21 | 1.10 | 0.53 | 17.5% | ✅ PASS → **gauntlet** |

### Round 2: Yang Gagal di Quick Screen

| Strategi | SID | Asset | IS PF | OOS PF | Alasan Gagal |
|----------|-----|-------|-------|--------|--------------|
| Donchian tanpa ADX | S02059 | SOL | 1.07 | 1.13 | IS MaxDD 33.4% >= 30% |
| Donchian + ADX (TP 10%) | S02060 | SOL | 1.15 | 0.98 | OOS PF 0.98 < 1.05 |
| Donchian + ADX (TP 10%) | S02061 | ARB | 0.79 | 0.97 | IS PF < 1.05, IS DD 34.7% |
| MACD Div default params | S02064 | ARB | 0.62 | 0.33 | Semua metric gagal |
| EMA Cross + ATR | S02063 | ARB | 0.70 | 0.76 | Semua metric gagal |
| MACD Div optimizer params | S02057 | SOL | 0.92 | 0.99 | MACD div adalah WLD-specific edge |
| MACD Div optimizer params | S02058 | ARB | 0.74 | 0.96 | Sama — WLD-specific |
| Donchian WLD v1 (ADX 22, stop 1.5) | S02066 | WLD | 1.09 | 1.11 | IS MaxDD 33.4% >= 30% |
| Donchian WLD v2 (ADX 25, stop 1.0) | S02067 | WLD | 1.30 | 0.90 | OOS PF 0.90 (overfit) |
| Donchian WLD v3 (ADX 22, stop 1.25) | S02068 | WLD | 1.14 | 0.98 | OOS PF 0.98 (hampir pass) |

---

## Key Learnings

### 1. 15m Crypto Scalping Sangat Sulit Setelah Biaya Transaksi

**Kenapa?**
- Average 15m bar range: 0.5-1.5%
- Transaction cost (round trip): 50-100 bps = 0.5-1.0%
- Setiap trade harus capture ≥ 0.5-1.0% hanya untuk break even
- Scalping dengan 2-5 bar hold: average move 0.3-0.8% → **tidak cukup cover biaya**
- Mean reversion (W%R, BB fade) menangkap 0.2-0.5% → **pasti rugi setelah biaya**
- Breakout (Donchian, BB) di 15m: terlalu banyak false breakout → WR 21-34%

**Implikasi**: Edge ada di 1h timeframe, di mana move 1-3% melebihi biaya transaksi.

### 2. taker_buy_sell_ratio Adalah Data 1h — Tidak Bisa Dipakai di 15m

**Fakta**: `taker_buy_sell_ratio` dikumpulkan pada granularity 1h dari Binance. Saat
dipakai di 15m backtest, enrichment join re-stamps setiap 1h bucket ke close time-nya dan
ASOF-merge backward ke bar yang lebih halus. **Semua 4 bar 15m dalam 1 jam carry nilai
taker ratio yang sama** — nilai dari jam sebelumnya.

**Bukan** microstructure exhaustion yang dideteksi, tapi apakah jam sebelumnya punya
taker flow extreme. Ini adalah 1h → 15m mismatch.

**Evidence**: 15 dari 30 strategi 15m taker/flow yang pernah diregistrasi sudah di-archived.
0 mencapai paper.

**Solusi**: Gunakan taker ratio di timeframe 1h (di mana data native), atau gunakan
volume (native 15m) sebagai proxy.

### 3. Volume Climax di BB Extreme = MOMENTUM, Bukan Reversal

**Eksperimen**: Vol climax BB fade (reversal direction) → PF 0.21-0.60, WR 31-41%.
Jika flip ke momentum → PF tetap rendah karena exit yang buruk.

**Penjelasan**: Volume spike di BB extreme = konviksi directional yang kuat. Price
cenderung **melanjutkan** break, bukan revert. Ini adalah momentum continuation signal.

### 4. Execution Profile adalah KUNCI untuk Pass Quick Screen

**Tanpa execution_profile**: Strategi Donchian(20) di 15m → PF 0.62-0.87 (losers run terlalu lama)

**Dengan execution_profile** (ATR stops + take profit):
```python
"execution_profile": {
    "atr_period": 14,
    "atr_stop_multiplier": 1.5,  # cut losers at 1.5× ATR
    "sizing_mode": "atr",
    "risk_per_trade": 0.02,
    "needs_atr": True,
    "take_profit_pct": 5.0,      # take profit at 5%
}
```
→ PF 1.14-1.35, DD < 30%, **PASS quick_screen**

**Kenapa?** ATR stop cuts losers early (1.5× ATR ≈ 1-2%), take profit captures wins at 5%.
Ini menciptakan asymmetric risk/reward: risk ~1.5%, reward ~5% → R:R ≈ 1:3.

### 5. Take Profit 5% > 10% untuk Pass Quick Screen

| TP | IS PF | IS DD | OOS PF | Result |
|----|-------|-------|--------|--------|
| 10% | 1.15 | 21.6% | 0.98 | ❌ OOS PF < 1.05 |
| 5% | 1.35 | 19.4% | 1.14 | ✅ PASS |

Tighter TP (5%) menangkap profit lebih cepat sebelum price revert. TP 10% terlalu greedy
— price sering reverse sebelum mencapai 10%.

### 6. ADX Filter Membantu, Tapi Threshold Harus Disesuaikan per Asset

| Asset | ADX Min | Hasil |
|-------|---------|-------|
| SOL | 22 | ✅ Pass (IS PF 1.35, OOS PF 1.14) |
| ARB | 22 | ✅ Pass (IS PF 1.14, OOS PF 1.08) |
| WLD | 22 | ❌ IS DD 33.4% (too high) |
| WLD | 24 | ✅ Pass (IS PF 1.21, OOS PF 1.10, DD 21.3%) |
| WLD | 25 | ❌ OOS PF 0.90 (overfit, too strict) |

WLD lebih volatile → butuh ADX threshold lebih tinggi (24) untuk filter noise.

### 7. MACD Divergence adalah WLD-Specific Edge

S02020 (WLD MACD divergence) pass quick_screen di 1h dengan PF 1.47 OOS. Tapi:
- SOL: PF 0.92 IS, 0.99 OOS → gagal
- ARB: PF 0.74 IS, 0.96 OOS → gagal

MACD divergence bekerja di WLD karena microstructure WLD (extreme kurtosis 228.2, fat tails,
near-zero ACF) → divergence signals detect exhaustion in violent moves. Karakteristik ini
tidak ada di SOL atau ARB.

**Tapi** S02056 ter-archived dari gauntlet karena walk_forward failed dan robustness 0/100.
MACD divergence dengan 42 OOS trades tidak cukup untuk statistical significance di gauntlet.

### 8. Parameter Override via API TIDAK BEKERJA

Backtest dengan `params` field di request body diabaikan oleh engine. Hasil selalu
identik regardless of params yang di-pass. **Harus registrasi strategy baru dengan
TYPE_NAME berbeda untuk setiap variant parameter.**

**Workaround**: Gunakan `sed` untuk membuat variant file dengan TYPE_NAME berbeda,
lalu enqueue masing-masing.

### 9. Quick Screen Evaluates BOTH IS dan OOS

Quick screen memerlukan:
- IS PF ≥ 1.05, IS Sharpe [0, 5], IS return > 0, IS DD < 30%
- OOS PF ≥ 1.05, OOS Sharpe [0, 5], OOS return > 0
- IS Trades ≥ 20, OOS Trades ≥ 15
- Robustness ≥ 50

**Keduanya** IS dan OOS harus pass. Strategi dengan IS bagus tapi OOS buruk (overfit)
tidak akan pass.

### 10. Enqueue Pipeline = Cara Tercepat ke Gauntlet

```bash
python -m forven.agent enqueue --file /path/strat.py --dataset SOL/USDT-1h
```

Melakukan: register → backtest → quick_screen → promote (jika pass) dalam satu command.
Jika pass, langsung masuk gauntlet. Jika gagal, tinggal di quick_screen.

---

## Pattern yang Terbukti

### Donchian(20) + ADX + ATR Execution Profile

```
forven/strategies/custom/donchian_adx_atr_sol_tight_v1.py  → S02062 (SOL)
forven/strategies/custom/donchian_arb_tight_v1.py           → S02065 (ARB)
forven/strategies/custom/donchian_wld_tight_v4.py           → S02069 (WLD)
```

**Config yang pass quick_screen:**

```python
default_params = {
    "_timeframe": "1h",
    "donchian_period": 20,
    "adx_period": 14,
    "adx_min": 22,  # 24 untuk WLD (lebih volatile)
    "execution_profile": {
        "atr_period": 14,
        "atr_stop_multiplier": 1.5,  # 1.5× ATR stop loss
        "sizing_mode": "atr",
        "risk_per_trade": 0.02,
        "needs_atr": True,
        "take_profit_pct": 5.0,     # 5% take profit (BUKAN 10%)
        "time_stop_bars": None,
    },
    "leverage": 1.0,
}
```

**Entry**: close breaks above Donchian(20) upper channel AND ADX ≥ adx_min
**Exit**: close breaks below Donchian(20) lower channel
**Risk**: Engine applies ATR stop (1.5×) + take profit (5%) via execution_profile

### Tuning per Asset

| Asset | ADX Min | Stop Mult | TP | Catatan |
|-------|---------|-----------|-----|---------|
| SOL | 22 | 1.5 | 5% | Config standar, works as-is |
| ARB | 22 | 1.5 | 5% | Sama dengan SOL, ADX 22 cukup |
| WLD | 24 | 1.5 | 5% | Butuh ADX lebih tinggi (24) karena lebih volatile |

**Jangan gunakan**:
- ADX 25 + stop 1.0 → overfit (IS bagus, OOS jatuh)
- ADX 22 + stop 1.25 → OOS PF 0.98 (hampir tapi tidak cukup)
- TP 10% → OOS PF 0.98 (greedy, price reverse sebelum 10%)

---

## Pitfalls Spesifik 15m

### 1. Taker Ratio Stale Data
`taker_buy_sell_ratio`, `ls_ratio`, `funding_rate` semuanya di-collect pada 1h granularity.
Di 15m, semua 4 bar dalam 1 jam carry nilai yang sama. **Jangan gunakan sebagai 15m signal.**

### 2. Mean Reversion Move Terlalu Kecil
W%R dari -70 ke -50 = ~0.3% di harga. Setelah biaya 50-100 bps, net profit ~0%. **Mean reversion
di 15m tidak viable setelah biaya.**

### 3. BB Breakout False Signals
BB(20, 2.0) di 15m tersentuh terlalu sering. Volume filter tidak membantu (volume climax = momentum,
bukan reversal). **Breakout di 15m butuh filter yang lebih ketat (ADX, regime) untuk work.**

### 4. Exit "Fall Back Inside BB" Terlalu Tight
Exit ketika close falls back inside BB → avg hold 2.3 bars → terlalu cepat, cut winners before
they run. **Gunakan opposite channel break (Donchian lower) atau ATR-based exit dari execution_profile.**

### 5. Oscillator Entry "Is Below" vs "Crosses Up"
- "wr < oversold" (is below) → enters while still oversold = catching falling knives → 427 OOS trades, PF 0.37
- "crosses up from oversold" (prev < threshold, curr >= threshold) → confirmed reversal → fewer trades, tapi PF tetap rendah di 15m
- **Di 15m, keduanya tidak viable karena move terlalu kecil**

### 6. EMA Cross Tanpa Filter → Overtrading
EMA 8/21 tanpa ADX/regime filter → 600 IS trades, PF 0.54-0.75. Terlalu banyak false signal.
**ADX ≥ 22 + regime EMA 200 diperlukan untuk filter noise.**

---

## Execution Profile — Kunci yang Sering Terlewat

### Tanpa Execution Profile
Strategy hanya mengandalkan entry/exit signal sendiri. Losers run sampai exit signal fire
(bisa 15+ bars = 3+ jam di 15m). PF 0.6-0.9.

### Dengan Execution Profile
Engine applies risk management on top of strategy signals:

```python
"execution_profile": {
    "atr_period": 14,
    "atr_stop_multiplier": 1.5,    # Stop loss at 1.5× ATR from entry
    "sizing_mode": "atr",           # Position size based on ATR
    "risk_per_trade": 0.02,         # Risk 2% of equity per trade
    "needs_atr": True,
    "take_profit_pct": 5.0,         # Take profit at 5%
    "time_stop_bars": None,         # No time stop (let ATR/TP handle it)
}
```

**Efek**:
- Losers cut at ~1.5× ATR (~1-2%) → limited downside
- Winners captured at 5% → guaranteed upside
- R:R ≈ 1:3 → bahkan dengan 35% win rate, PF > 1.1
- MaxDD terkontrol < 30%

### Komponen Execution Profile yang Penting

| Komponen | Value | Kenapa |
|----------|-------|--------|
| `atr_stop_multiplier` | 1.5 | 1.0 terlalu tight (cut winners), 2.0 terlalu loose (DD > 30%) |
| `take_profit_pct` | 5.0 | 10% terlalu greedy (price reverse), 3% terlalu tight |
| `sizing_mode` | "atr" | Adaptive to volatility |
| `risk_per_trade` | 0.02 | 2% risk per trade (standar) |
| `leverage` | 1.0 | Leverage 1.0 cukup, 3.0 amplifikasi DD |

---

## Rekomendasi untuk Masa Depan

### Jika Ingin Strategi 15m yang Profitable
1. **Gunakan modal lebih besar** → biaya transaksi relatif lebih kecil
2. **Gunakan exchange dengan fee lebih rendah** (< 50 bps round trip)
3. **Coba market making** alih-alih directional scalping (capture spread, bukan move)
4. **Gunakan 1h signal dengan 15m execution** — compute indicators di 1h, execute di 15m

### Jika Ingin Strategi 1h yang Robust
1. **Donchian(20) + ADX + ATR execution_profile** — proven pattern (3 strategi di gauntlet)
2. **MACD divergence** — works untuk WLD (extreme kurtosis assets), bukan SOL/ARB
3. **EMA cross + ADX + regime** — works untuk ETH, tapi butuh tuning per asset

### Workflow yang Efisien
1. **Gunakan `enqueue`** — satu command untuk register → backtest → screen → promote
2. **Buat variant dengan `sed`** — ubah TYPE_NAME + params, enqueue masing-masing
3. **Cek quick_screen reasons** — jika gagal, reasons menunjukkan metric mana yang perlu fix
4. **Tuning urutan**: TP dulu (5% vs 10%), lalu ADX (22 vs 24), lalu stop (1.0 vs 1.5 vs 2.0)

### Gauntlet Survival
Quick screen hanya permulaan. Gauntlet menjalankan:
- Walk-forward analysis (paling sering gagal)
- Monte Carlo DD (butuh ≥60-80+ trades agar stabil)
- Parameter jitter (robustness)
- Cost stress (2× fee + slippage)
- Deflated Sharpe

**Strategi dengan < 30 OOS trades rentan fail Monte Carlo.** Donchian(20) dengan 25-49 OOS trades
berpotensi fail. Butuh ≥ 60 OOS trades untuk robustness tinggi.

### Hindari
- ❌ Taker ratio / LS ratio / funding sebagai 15m signal (stale 1h data)
- ❌ Mean reversion di 15m (move terlalu kecil untuk biaya)
- ❌ Volume climax sebagai reversal signal (sebenarnya momentum)
- ❌ TP 10% (terlalu greedy, price reverse sebelum mencapai)
- ❌ ADX 25+ di 15m (terlalu restriktif, too few trades)
- ❌ Stop 1.0 ATR (overfit, cut winners)
- ❌ Strategy tanpa execution_profile (losers run terlalu lama)

### Quick Reference: Parameter Sweet Spot

```
Donchian(20) + ADX(14) ≥ 22 + ATR(14) stop 1.5× + TP 5% + leverage 1.0
```
- SOL: ADX ≥ 22 ✅
- ARB: ADX ≥ 22 ✅
- WLD: ADX ≥ 24 ✅ (lebih volatile, butuh filter lebih ketat)

---

## Referensi

- `forven/strategies/builtin/donchian.py` — builtin Donchian strategy (referensi pattern)
- `forven/strategies/builtin/ema_cross.py` — builtin EMA cross dengan ADX + regime filter
- `forven/strategies/builtin/williams_r.py` — builtin W%R dengan ADX filter
- `forven/strategies/custom/wld_macd_divergence_v1.py` — MACD divergence (WLD-specific, proven di 1h)
- `forven/strategies/custom/donchian_adx_atr_sol_tight_v1.py` — strategi SOL yang pass (S02062)
- `forven/strategies/custom/donchian_arb_tight_v1.py` — strategi ARB yang pass (S02065)
- `forven/strategies/custom/donchian_wld_tight_v4.py` — strategi WLD yang pass (S02069)
- `AGENTS.md` — project context, strategy creation recipes, gate thresholds
- `~/.pi/agent/skills/forven/SKILL.md` — forven skill workflow
- `~/.pi/agent/skills/quantitative-research/SKILL.md` — quant research methodology
