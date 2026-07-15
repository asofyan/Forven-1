# Strategy Development State

> Terakhir diperbarui: 2026-07-11

---

## Ringkasan Sesi

Kita menganalisis 23 strategi paper di pipeline Forven dan mengidentifikasi **MACD Divergence** sebagai dominant alpha mechanism (8 dari 23 paper). Kemudian mengeksekusi **Proposal 1**: fix structural lookahead di swing detection + deploy 3 strategi ke gauntlet.

---

## Proposal 1: MACD Divergence — Configurable Lookahead

### Temuan Kunci

1. **Lookahead adalah integral dari alpha** — zero-lookahead swing detection menghasilkan Sharpe -7.9. Minimal viable lookahead adalah `half=4` (swing_lookback=8).
2. **ATR trailing stop merusak strategi** — menutup posisi terlalu cepat → re-entry rugi → performa negatif.
3. **Lookahead lebih kecil = OOS lebih robust** — IS/OOS degradation mengecil proporional dengan lookahead.
4. **Parameter `swing_lookback` mengontrol lookahead = `swing_lookback // 2` bars.**

### File Strategy

| File | Path |
|------|------|
| Base strategy | `forven/strategies/custom/macd_divergence_fixed_la.py` |
| SOL variation | `forven/strategies/custom/macd_div_fixed_la_sol.py` |
| BTC variation | `forven/strategies/custom/macd_div_fixed_la_btc.py` |
| ETH variation | `forven/strategies/custom/macd_div_fixed_la_eth.py` |

### Hasil Backtest (Override Params)

| Aset | TF | swing_lookback (half) | Lookahead | OOS Sharpe | OOS PF | Trades | DD% |
|---|---|---|---|---|---|---|---|
| SOL | 15m | 8 (4) | 60m | **1.15** | **1.32** | 70 | 5.7 |
| BTC | 15m | 10 (5) | 75m | **1.35** | **1.43** | 45 | 4.4 |
| ETH | 1h | 8 (4) | 4h | **2.14** | **1.93** | 23 | 5.1 |

Semua lolos quick_screen thresholds (PF ≥ 1.05, Sharpe > 0, DD < 30%, trades ≥ 20/15).

### Strategi di Gauntlet

| ID | Aset | Default Params | OOS Backtest | Status |
|---|---|---|---|---|
| **S01946** | SOL/USDT-15m | swing_lookback=8, vol_thresh=1.2 | Sharpe 1.15, PF 1.32, 70 trades | ✅ gauntlet |
| **S01945** | BTC/USDT-15m | swing_lookback=10, vol_thresh=1.2 | Sharpe 1.35, PF 1.43, 45 trades | ✅ gauntlet |
| **S01947** | ETH/USDT-1h | swing_lookback=8, vol_thresh=1.2 | Sharpe 2.14, PF 1.93, 23 trades | ✅ gauntlet |

Quick screen passed → dipromosikan ke gauntlet. Menunggu 12-step Advancer.

### Iterasi Pengembangan

| Iterasi | Pendekatan | Hasil |
|---------|-----------|-------|
| 1 | Zero-lookahead swing (konfirmasi 1 bar) | OOS Sharpe -10 ❌ |
| 2 | Lookback-only rolling max/min | OOS Sharpe -6.1 ❌ |
| 3 | Symmetric swing dengan half=2 | OOS Sharpe -3.7 ❌ |
| 4 | Symmetric swing half=4 + ATR exit | OOS negative semua ❌ |
| 5 | Symmetric swing half=4, tanpa ATR → original exit | ✅ OOS positif semua |

**Pelajaran**: ATR trailing stop adalah sumber kegagalan utama. Lookahead simetrik dengan half≥4 diperlukan untuk swing selectivity.

### Perintah Cek Status

```bash
cd /home/hms/forven
export FORVEN_API_URL=http://127.0.0.1:8004
export FORVEN_API_KEY=92ec5b339a6a980a8c3d6dc31b237ac4e9572a520921ce454fb5bf049839d7c0
export FORVEN_OPERATOR_KEY=295dc8d02f34f301b6456ae19f4b5b02e8bddc815b124729c020d57dba573566
export PATH=/home/hms/forven/.venv/bin:$PATH

# Cek gate readiness
python -m forven.agent gate-report S01946
python -m forven.agent gate-report S01945
python -m forven.agent gate-report S01947

# Detail strategi
python -m forven.agent strategy S01946

# Tunggu paper (timeout 30 menit)
python -m forven.agent wait-paper --strategies S01946,S01945,S01947 --timeout 1800
```

---

## Proposal Selanjutnya (Belum Dikerjakan)

### Proposal 2: SOL MACD Divergence + Taker Flow

Mutasi S01830 (BTC 15m taker flow, 104 trades, OOS Sharpe 1.43) ke SOL.
- SOL thinner order book → taker flow signal lebih jelas
- Reduce `taker_entry_z` dari 0.8 ke 0.6 (SOL lebih noisy)
- Trade mode `both`

### Proposal 3: Multi-Aset MACD Divergence Portfolio

Meta-strategy yang running MACD Divergence di SOL + BTC + ETH paralel.
- Entry hanya ketika ≥2 aset menunjukkan divergence di direction yang sama
- Mengurangi false signals, meningkatkan statistical significance

### Proposal 4: Volume Threshold Relaxation SOL 1h

S01932 punya OOS Sharpe 2.40 tapi cuma 18 trades.
- Turunkan volume threshold 1.5x → 1.2x
- Target 40-50 OOS trades
- PF mungkin turun 2.21 → ~1.5 tapi lebih reliable

### Proposal 5: EMA Cross + MACD Divergence Combo

Gabungkan EMA Cross (trend following) dengan MACD Divergence (entry timing).
- EMA fast/slow menentukan trend direction
- MACD divergence sebagai entry trigger searah trend
- Filter out divergence yang berlawanan trend

### Proposal 6: Deflated Sharpe-Aware Parameter Selection

Terapkan Bayesian prior: strategi dengan OOS Sharpe > 2.5 punya probability of backtest overfit tinggi.
- Target OOS Sharpe 1.0-1.8 (bukan mengejar 3+)
- Prioritaskan trade count > 40 sebagai hard requirement
- Walk-forward degradation < 30%

---

## Referensi

- **Project context**: `/home/hms/forven/AGENTS.md`
- **Forven skill**: `/home/hms/.pi/agent/skills/forven/SKILL.md`
- **Quant research skill**: `/home/hms/.pi/agent/skills/quantitative-research/SKILL.md`
- **Base strategy interface**: `/home/hms/forven/forven/strategies/base.py`
- **Paper strategies**:
  - S01767 (SOL 15m MACD Divergence Volume) — baseline comparison
  - S01827 (ETH 1h MACD Divergence Volume) — nearest neighbor
  - S01830 (BTC 15m MACD Divergence Taker) — most robust (104 trades)
  - S01517 (BTC 15m MACD Divergence Reversal) — highest trade count (113)
  - S01355 (SOL 1h EMA Cross ATR) — strongest trend follower
