# Brief: Leverage-Aware Simulator + Shadow Mode (Paper vs Real Divergence Learning)

Companion dari `fib-gann-validation-brief.md`. Scope: `trade_simulator.py` diperluas jadi dua kemampuan — (1) leverage/liquidation-aware simulation, (2) shadow mode yang jalan paralel dengan trade uang beneran dan mengukur+mempelajari divergensinya.

## 0. Keputusan urutan (jawaban untuk pertanyaan "mana yang dibangun duluan")

1. **SEKARANG — Opsi 1**: leverage/liquidation-aware simulator. Buildable tanpa data trade real, fondasi semua fitur di bawah.
2. **SETELAHNYA — Opsi 2**: perluas `trade_annotation` dengan kolom eksekusi real (leverage, margin_mode, entry/exit fill real, fees real, PnL real). Ini jadi sisi "real" dari pasangan shadow.
3. **BELUM — Opsi 3** (execution/CCXT order otomatis): tetap Fase 3+. Shadow mode TIDAK butuh eksekusi otomatis — trade real diisi manual founder via trade_annotation dulu.

> **Verifikasi Claude Code (3 Juli 2026)**: Opsi 1 (bag. 1-2 di bawah) SUDAH DIIMPLEMENTASI — lihat `docs/fib-gann-validation-brief.md` bag. 13 utk desain final, hasil verifikasi thd data real, dan 1 penyesuaian dari spek asli (representasi `initial_margin` sbg fraksi notional, bukan dolar — modul ini gak pernah nge-track notional/equity dolar sama sekali). **Opsi 2 (perluasan `trade_annotation`, bag. 7 poin 3) SEKARANG JUGA SUDAH DIIMPLEMENTASI** — migration `0005_trade_annotation_execution_columns.py`, 7 kolom nullable, detail lengkap + verifikasi upgrade/downgrade thd Postgres lokal di `docs/fib-gann-validation-brief.md` bag. 14. **Ini path CODEOWNERS-protected (`packages/db/migrations/`) — butuh review manual founder sebelum merge**, gak di-auto-merge walau CI hijau. Poin 4-6 (shadow_pair pairing, fidelity score, ML risk envelope) BELUM dikerjakan — nunggu founder mulai isi kolom baru ini dari trade real.

## 1. Konsep inti: setiap trade real punya kembaran simulasi

Saat founder entry pakai uang beneran berdasarkan sinyal (atau manual-tapi-searah-sinyal):

- Simulator **tetap jalan** untuk sinyal yang sama, dengan aturan baku (entry di harga sinyal, SL/TP dari spec brief utama bag. 5, fill ideal).
- Kedua hasil dicatat sebagai **satu pasangan** (`shadow_pair`): `sim_trade` vs `real_trade` dengan `signal_id` yang sama.
- Dari pasangan ini dihitung **divergence score** — bukan cuma "beda PnL berapa", tapi dekomposisi PENYEBAB bedanya (bag. 3).

Tujuan akhir: agent memahami bahwa eksekusi uang beneran ≠ paper, dan tahu PERSIS komponen mana yang menyebabkan gap, lalu belajar mengatur risk envelope (bag. 5) supaya gap-nya mengecil.

## 2. Leverage/liquidation-aware simulation — spesifikasi

Tambahan state per posisi simulasi:

```python
@dataclass
class MarginContext:
    leverage: float                 # e.g. 10.0
    margin_mode: Literal["cross", "isolated"]
    initial_margin: float           # notional / leverage
    maintenance_margin_rate: float  # dari tier exchange (Binance: bertingkat by notional)
    liquidation_price: float        # dihitung, bukan diinput
```

Aturan wajib:

- **Liquidation check SEBELUM SL check** di setiap candle/intrabar step: kalau `liquidation_price` tersentuh sebelum SL struktural → exit_reason = `LIQUIDATED`, PnL = -initial_margin (isolated) — BUKAN sekadar loss sebesar jarak SL. Ini perbedaan paling material antara paper naive dan real.
- Liquidation price dihitung dari formula margin exchange target (Binance USDT-M sebagai default; maintenance margin tier by notional). Simplifikasi diperbolehkan untuk MVP (flat MMR per simbol) asal dicatat sebagai asumsi.
- **Funding cost** ikut mengurangi margin available (bukan cuma dikurangkan di akhir) — posisi leverage tinggi yang di-hold lama bisa ke-liquidasi karena erosi funding, simulator harus bisa menangkap ini.
- Fees taker/maker entry+exit dihitung dari notional (bukan margin).

### Invariant yang harus di-enforce (fail-fast, bukan warning):

```
liquidation_price HARUS lebih jauh dari SL struktural + buffer
```

Kalau pada leverage yang diminta liquidation price jatuh DI DALAM jarak SL → posisi itu tidak valid untuk leverage tsb. Ini yang melahirkan konsep **max_safe_leverage** (bag. 5).

## 3. Divergence attribution — dekomposisi paper vs real per pasangan

Total gap = `real_pnl_pct - sim_pnl_pct`, didekomposisi menjadi komponen additive (masing-masing % dari notional):

| Komponen | Definisi | Sumber data |
|---|---|---|
| `entry_slippage` | (real_fill_entry - signal_price) × arah | trade_annotation vs signal |
| `exit_slippage` | (real_fill_exit - sim_exit_price) × arah, untuk exit_reason yang sama | trade_annotation vs sim |
| `timing_deviation` | founder entry lebih awal/telat dari candle sinyal (harga referensi beda) | timestamp real vs signal |
| `size_leverage_effect` | dampak leverage/margin real beda dari baseline sim (termasuk kasus LIQUIDATED vs SL) | MarginContext real vs sim |
| `fees_funding_delta` | selisih fee tier + funding aktual vs asumsi sim | exchange data vs sim |
| `manual_override` | founder exit di titik yang bukan TP/SL sistem (discretionary exit) | exit_reason real ≠ sim |
| `residual` | sisa yang tidak terjelaskan (harus kecil; kalau besar = ada bug attribution) | hitung terakhir |

Simpan per pasangan ke tabel/log `shadow_pair` + agregasi rolling (mis. 30 pasangan terakhir): komponen mana yang paling dominan menyumbang gap. **Ini output paling berharga untuk founder** — misal kalau 70% gap ternyata dari `manual_override`, masalahnya disiplin eksekusi, bukan sinyal; kalau dari `size_leverage_effect`, masalahnya sizing.

## 4. Fidelity score

Skor 0–100 per pasangan: seberapa dekat eksekusi real terhadap simulasi ideal.

```
fidelity = 100 - Σ(|komponen_i| × weight_i, dinormalisasi terhadap risk per trade)
```

- Weight awal rule-based (bukan ML): slippage & fees weight kecil (tak terhindarkan), manual_override & size_leverage_effect weight besar (bisa dikendalikan).
- Rolling fidelity < threshold (mis. 70) → surface warning ke founder via Telegram layer: "eksekusi real lo makin jauh dari sistem, komponen terbesar: X".

## 5. ML risk envelope — yang dipelajari dan yang TIDAK BOLEH dipelajari

**PRINSIP KERAS (jangan dilanggar walau diminta):** ML TIDAK menentukan "kapan boleh max leverage". Leverage adalah OUTPUT dari struktur trade, bukan input yang dimaksimalkan:

```
risk_amount      = equity × risk_pct_per_trade        # hard cap rule-based, mis. 1-2%
qty              = risk_amount / |entry - SL|
required_margin  = qty × entry / leverage
max_safe_leverage = leverage tertinggi di mana liquidation_price
                    masih ≥ buffer_k × ATR di luar SL struktural
leverage_used    = min(leverage_diminta, max_safe_leverage)
```

**Yang BOLEH dipelajari ML** (dalam batas hard cap, dari data shadow_pair + triple-barrier outcomes):
- `buffer_k` optimal per regime/simbol (jarak aman liquidation vs SL)
- `risk_pct_per_trade` adjustment per confidence score & regime (dalam range, mis. 0.5–2%, TIDAK PERNAH di atas cap)
- Max concurrent positions & margin ratio cap per regime (mis. total margin used / equity ≤ X%, X dipelajari per regime dalam range 20–60%)
- Prediksi `manual_override` risk: kondisi apa yang secara historis bikin founder menyimpang dari sistem (untuk warning preventif, bukan untuk blokir)

**Yang TIDAK BOLEH dipelajari / hard-coded rule:**
- Absolute max leverage cap per simbol (set manual, mis. 10-20x majors, lebih rendah alts)
- Minimum jarak liquidation-vs-SL (floor untuk buffer_k)
- Kill-switch drawdown harian/mingguan
- R:R gate ≥ 1.5 (dari brief utama bag. 5c)

**Cold start**: sebelum ada ≥ ~50 pasangan shadow, SEMUA parameter di atas pakai default rule-based. ML fitting baru diaktifkan setelah data cukup, dan hasil fitting harus lolos walk-forward yang sama (packages/backtest-core) sebelum dipakai — bukan langsung live.

## 6. Skema data minimum

```
shadow_pair:
  signal_id, symbol, timeframe, regime
  sim: {entry, exit, exit_reason, leverage, margin_mode, pnl_pct, funding_pct, fees_pct}
  real: {entry_fill, exit_fill, exit_reason, leverage, margin_mode, pnl_pct, funding_pct, fees_pct,
         entry_ts, exit_ts}   # dari trade_annotation yang diperluas (Opsi 2)
  attribution: {entry_slippage, exit_slippage, timing_deviation, size_leverage_effect,
                fees_funding_delta, manual_override, residual}
  fidelity_score: float
```

`trade_annotation` diperluas dengan: `leverage, margin_mode, entry_fill_price, exit_fill_price, fees_paid, funding_paid, exit_reason_real`. Sinyal tanpa trade real tetap disimulasikan dan dicatat (sisi real kosong) — itu tetap data untuk kalibrasi bobot confluence.

## 7. Urutan implementasi yang disarankan

1. `MarginContext` + liquidation check + funding-erosion di `trade_simulator.py` (+ unit test: liquidasi sebelum SL pada leverage tinggi, funding erosion memicu liquidasi, cross vs isolated beda perilaku)
2. `max_safe_leverage` formula + invariant fail-fast
3. Perluasan skema `trade_annotation` (Opsi 2)
4. `shadow_pair` pairing + divergence attribution + fidelity score
5. Agregasi rolling + Telegram surfacing
6. ML risk envelope — PALING TERAKHIR, setelah data cukup (bag. 5 cold start)

Poin 1-2 bisa dikerjakan sekarang tanpa input tambahan founder. Poin 3 butuh founder mulai disiplin mencatat trade real. Poin 6 jangan dikerjakan sebelum poin 1-5 stabil dan data terkumpul.
