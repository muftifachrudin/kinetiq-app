# Brief: Desain Regime Gate (FREEZE/RISK_OFF) & kNN Risk Memory (Risk Hard Gate Layer 3)

Desain (bukan implementasi) untuk 2 dari 4 sub-gate ENGGANG Layer 3 yang
sejak `execution/risk_gate.py` v1 (13 Juli 2026) eksplisit ditandai "belum
ada desain sama sekali" (`docs/kanban.md`, `docs/prd.md` §3.1/§6 Fase 2).
Mengikuti konvensi proyek ini sendiri — setiap komponen besar yang belum
jelas selalu dapat brief desain dulu sebelum jadi slice implementasi
(`docs/margin-mode-brief.md`, `docs/shadow-simulator-brief.md`,
`docs/fib-gann-validation-brief.md`) — dokumen ini TIDAK mengubah kode
apa pun. Sesi implementasi berikutnya baru dimulai setelah brief ini
disetujui, dan hasilnya tetap harus lolos walk-forward sebelum dipakai
sebagai gate hidup (§8-9).

Riset untuk brief ini menemukan sesuatu yang mengubah asumsi sesi
sebelumnya: infrastruktur untuk memvalidasi kedua gate ini **sudah ada
dan sudah pernah dipakai** di
`apps/products/trading/agent-orchestrator/validation/fib_gann_backtest/gated_campaign.py`
— termasuk classifier regime causal (`trailing_drift()`) dan mekanisme
promosi walk-forward (`GateConfig`/`apply_gates()`/`PF_PASS_FRACTION`).
Desain di bawah ini memperluas infrastruktur itu, bukan membangun dari
nol.

## 1. Dua konsep "regime" yang harus dipisah tegas

`gated_campaign.py` (dibangun sebelumnya, Fase 6b I2) sudah punya
`trailing_drift()`/`regime_by_signal_index()`/`campaign.classify_regime()`
— classifier **bull/bear/range berbasis drift harga trailing 30 hari**,
dipakai `GateConfig(use_regime_direction_gate=True)` (`veto_short_bull`,
`veto_both_counter_trend`) untuk memveto trade LAWAN tren. Ini **BUKAN**
regime gate yang dimaksud PRD §3.1 Layer 3 ("FREEZE/RISK_OFF → no-trade").
Bedanya prinsipil:

- **Regime-direction gate (sudah ada)**: soal ARAH — apakah trade ini
  melawan tren mayor. Konsekuensinya kalau salah arah: veto SATU SISI
  (SHORT saat bull, atau LONG saat bear), bukan blokir semua trading.
- **Regime gate PRD (belum ada, target brief ini)**: soal RISIKO/
  VOLATILITAS — apakah kondisi pasar SEDANG BERBAHAYA untuk trading APA
  PUN, arah manapun. FREEZE = stop total, RISK_OFF = kurangi eksposur.
  Ini konsep "tail-risk regime", bukan "trend regime".

**Temuan penting yang membentuk desain di §3**: regime-direction gate
yang sudah dites nyata (4 seri, campaign penuh) **GAGAL kriteria
promosi** — window lolos terbaik cuma 34% (12/35), butuh ≥66,66%
(`PF_PASS_FRACTION = 0.6666`, `campaign.py:60`). Ini preseden empiris
langsung dari codebase ini sendiri: gate berbasis regime, walau dihitung
causal dengan benar, tidak otomatis lolos ambang adopsi proyek ini. Jadi
regime gate versi PRD (volatilitas) harus diperlakukan dengan skeptisisme
yang sama, bukan diasumsikan akan berhasil.

## 2. Desain: Regime gate berbasis volatilitas (FREEZE/RISK_OFF)

**Fitur**: volatilitas realized trailing (mis. ATR(14)/close, atau stdev
return log, window 14-30 hari) dihitung causal — pola persis
`trailing_drift()` (`gated_campaign.py:187-209`): bisect ke `candle_ts`,
hanya pakai candle `ts <= as_of_ts`, `None` kalau histori trailing belum
cukup (bukan exception, bukan 0 — konsisten dengan fallback "unknown,
never vetoed" yang sudah dipakai di seluruh modul ini).

**Threshold**: percentile rank volatilitas hari ini vs. seluruh histori
volatilitas *sampai hari itu* (expanding window, tetap causal — mirip
`derivatives_context._percentile_rank(value, population)`,
`derivatives_context.py:117-127`, cuma populasinya trailing bukan
snapshot). Starting point (angka bebas, adopsi yang memutuskan — sama
persis konvensi `DEFAULT_ZIGZAG_ATR_MULTIPLIER`/`ETA_SAFETY_FACTOR`):

```
percentile >= 0.975  -> FREEZE    (no-trade, semua arah)
percentile >= 0.90   -> RISK_OFF  (size-down, bukan veto total)
selainnya             -> NORMAL
```

**Konfirmasi sekunder opsional (OI-fuel)**: `derivatives_context.
FuelQuadrant` (`derivatives_context.py:78`) sudah membuktikan hari
fuel-confirmed bergerak 1.8-2.7x lebih jauh (`CLAUDE.md`, F6/F7) — ini
sinyal volatilitas-regime yang SUDAH tervalidasi, tinggal dipakai sebagai
konfirmasi tambahan (menaikkan level RISK_OFF->FREEZE, TIDAK PERNAH
menurunkan, sama aturan satu-arah yang sudah dipakai `HIGH_VOL_RISK_
MULTIPLIER` di `position_sizing.py`). **Harus opsional/graceful-degrade**:
`open_interest` production saat ini **0 baris** (`docs/sonnet5-
implementation-roadmap.md:236`) — classifier harus jalan penuh dengan
OHLCV saja dan hanya memakai OI-fuel kalau datanya ada.

**Output**: `enum MarketRegimeState { NORMAL, RISK_OFF, FREEZE }`,
mengikuti pola `regime_by_signal_index()` — dict `signal.index -> state`,
bukan dihitung ulang per-sinyal.

## 3. Regime gate — jalur validasi (reuse langsung, bukan harness baru)

Tambahkan SATU field baru ke `GateConfig` (`gated_campaign.py:152-162`):
`use_volatility_regime_gate: bool = False`, diproses di `apply_gates()`
persis pola `use_regime_direction_gate` yang sudah ada (baris 284-292) —
FREEZE memveto semua sinyal terlepas arah; RISK_OFF **tidak divalidasi
sebagai veto**, tapi lewat mekanisme `SizingConfig`/`size_multiplier()`
yang SUDAH ADA (baris 469-510) sebagai pengurang size, bukan reject.
Dijalankan lewat `run_gated_series_batch()` yang sudah ada, 4 seri
produksi yang sama (`campaign.SERIES`).

**Kriteria adopsi diusulkan BEDA dari gate lain di modul ini** — gate lain
(`confidence_only`, `trend_alignment_only`, dst.) semua dinilai murni
dari kenaikan PF net. Regime gate ini tujuannya mengurangi tail-risk,
bukan menaikkan PF — jadi `promoted` versi lama (PF net naik di ≥66,66%
window) bisa salah arah (regime gate yang BENAR justru bisa membuat PF
net FLAT sambil mengurangi drawdown terburuk). Diusulkan bar dua bagian:
(a) PF net tidak turun material vs `no_gate` baseline di ≥4/6 window,
DAN (b) `pooled_pf_net_ci90`/drawdown terburuk per window (butuh metrik
baru, lihat §9) membaik. Ini **keputusan desain terbuka**, bukan
diklaim final — didiskusikan ulang begitu angka nyata masuk.

**Batasan data yang membatasi validasi ini dari awal**: histori OHLCV
production ~1 tahun, didominasi SATU rezim (bear) — sudah diketahui
sebagai gap (`docs/sonnet5-implementation-roadmap.md` P1 backlog,
"1 tahun data = dominan SATU rezim", butuh 2-3 tahun/~26k candle). Hasil
validasi regime gate dari data 1 tahun ini akan lemah untuk rezim
bull/range — sebaiknya backfill P1 jalan duluan atau paralel, bukan
diabaikan.

## 4. Desain: kNN risk memory

**Tidak ada infrastruktur kNN sama sekali di repo ini** (dikonfirmasi:
`sklearn.neighbors`/`NearestNeighbors`/distance-metric tidak ada di
manapun) — beda dari regime gate, ini benar-benar dibangun baru, tapi
tetap memakai komponen yang sudah ada:

- **Corpus training**: 2.679 trade simulasi triple-barrier-labeled dari
  replikasi 4 seri (`fit_weights.LabeledSignal`/`build_labeled_signals()`
  — corpus yang SAMA dipakai `fit_weights.py` untuk logistic regression),
  **BUKAN** 276 baris `trade_annotation` real. `docs/kanban.md` sendiri
  sudah menyimpulkan 276 baris (mayoritas `leverage`/`exit_reason_real`
  NULL) terlalu tipis untuk "kemiripan ke histori rugi" yang berarti —
  2.679 baris simulasi jauh lebih memadai secara jumlah, meski beda
  sifat (simulasi vs real, lihat §6 poin terbuka).
- **Feature vector**: `fit_weights.ALL_CANDIDATE_FEATURE_NAMES`/
  `_feature_vector()` (`fit_weights.py:134-162`) — sudah 0-1-scaled by
  construction ("every factor already 0-1, no scaling needed", catatan
  `fit_weights.py` sendiri), pas untuk Euclidean distance tanpa
  normalisasi tambahan.
- **Split per-window**: `fit_weights.split_by_window()` — TRAIN kNN
  index HANYA dari window train (no lookahead), sama pola
  `_fit_confidence_model()`/`MIN_TRAIN_SAMPLES` (baris 228-248
  `gated_campaign.py`) untuk guard data terlalu sedikit.

**Algoritma per window**:
```
model = sklearn.neighbors.NearestNeighbors(n_neighbors=k)
model.fit(train_feature_vectors)                      # TRAIN window ini saja
for setiap sinyal kandidat di TEST window:
    neighbor_idx = model.kneighbors(candidate_vector, k)
    loss_fraction = fraksi neighbor yang outcome-nya STOP_LOSS
    if loss_fraction > threshold: veto (atau size-down, simetris dgn §3)
```
Kalau train window terlalu kecil (< `MIN_TRAIN_SAMPLES`, sama konstanta
`fit_weights.py`), lewati gate untuk window itu — pola "skip_reason,
jangan fabricate" yang sudah konsisten dipakai di seluruh harness ini.

**k dan threshold**: starting point `k=10`, `threshold=0.6` (>60% dari
10 tetangga terdekat berakhir SL → veto) — angka bebas, bukan final,
di-sweep grid kecil (`k ∈ {5,10,20}`, `threshold ∈ {0.5,0.6,0.7}`) sama
persis pola `confidence_percentile` sweep yang sudah ada, laporkan semua
kombinasi bukan cuma yang menang.

## 5. Distance metric — pertanyaan terbuka

Euclidean dipilih sebagai default (standar `NearestNeighbors`, cocok
untuk fitur yang sudah 0-1-scaled seragam), tapi cosine distance belum
dicoba/dibandingkan — fitur konfluen (swing_quality, fib_gann_confluence,
dst.) berpotensi lebih relevan diukur dari POLA relatif antar-faktor
ketimbang jarak absolut. Diusulkan dites keduanya di walk-forward yang
sama (§6), bukan diasumsikan salah satu benar dari awal.

## 6. kNN risk memory — jalur validasi + isu real-vs-simulasi

Sama pola §3: tambahkan `use_knn_risk_memory_gate` ke `GateConfig`,
proses di `apply_gates()`, jalankan lewat `run_gated_series_batch()` yang
sudah ada, kriteria promosi `PF_PASS_FRACTION` (0,6666) yang SAMA dipakai
gate lain di modul ini — ini genuinely gate "kualitas sinyal" (mirip
`confidence_only`), jadi bar PF-net standar cocok, tidak perlu bar dua
bagian seperti regime gate.

**Pertanyaan terbuka yang sengaja TIDAK dijawab brief ini**: apakah 276
baris `trade_annotation` real (begitu cukup banyak, lolos ambang cold-
start ≥50 pasang yang sudah dipakai `docs/shadow-simulator-brief.md`
§5 untuk ML risk envelope) nanti DIGABUNG ke corpus 2.679 trade simulasi,
atau dijaga terpisah? Trade real dan simulasi punya distribusi berbeda
(real kena slippage/eksekusi manusia nyata, execution fields-nya sendiri
mayoritas NULL) — mencampur tanpa cek comparability dulu berisiko bias
diam-diam. Keputusan ini didokumentasikan di sini SUPAYA sesi
implementasi tidak menebak, bukan dijawab sekarang.

## 7. Jalur ke produksi (SETELAH lolos validasi, bukan bagian sesi ini)

`gated_campaign.py`/`fit_weights.py` hanya jalan di backtest (array
candle historis penuh) — beda dari `execution/risk_gate.py` yang
DB-free, pure-function, dipanggil live per-sinyal. Begitu regime gate
atau kNN risk memory lolos ambang adopsi masing-masing (§3/§6), langkah
PORTING ke produksi (sesi implementasi TERPISAH, bukan bagian brief ini):

1. Pindahkan algoritma yang terbukti ke modul pure `skills/strategy/`
   (`market_regime.py`/`risk_memory.py`) — DB-free, ikut disiplin
   `fib_gann_timing.py`/`position_sizing.py` (lihat `CLAUDE.md`).
2. kNN butuh corpus "beku" untuk live inference (tidak ada window
   walk-forward di live trading) — usul: refit periodik (mis. mingguan)
   dari seluruh corpus tersedia, diserialisasi jadi artifact yang dibaca
   modul live. Ini detail operasional BARU yang backtest tidak perlu
   pikirkan — dicatat di sini supaya tidak lupa saat implementasi.
3. `RiskMandateSnapshot` (`execution/risk_gate.py`) diperluas dengan
   field baru (mis. `regime_state`, `knn_veto`) yang diisi orkestrator
   (belum ada, `graphs/` masih kosong) sebelum masuk
   `evaluate_risk_gate()` — `risk_gate.py` sendiri TIDAK berubah logika
   intinya, cuma menerima input baru.
4. Sampai lolos (2), kedua gate HANYA jalan sebagai laporan/narasi (mis.
   lewat `metrics.compute_metrics_by_regime()`'s pluggable `regime_of`
   yang sudah ada, `fib-gann-validation-brief.md:589`) — tidak pernah
   memblokir order sungguhan. Sama disiplin LLM Arbiter (feature-flag
   OFF default, dibandingkan A/B).

## 8. Yang eksplisit TIDAK termasuk brief ini

- Kode implementasi apa pun (modul baru, `GateConfig` field baru) — itu
  sesi berikutnya, setelah brief ini disetujui.
- Menjalankan validasi nyata (belum ada angka PF/promoted sungguhan
  untuk kedua gate ini) — brief ini desain, bukan hasil eksperimen.
- Daily-loss-limit/drawdown otomatis & correlation-based exposure cap
  (2 sub-gate exposure caps lain) — tetap di luar scope, alasannya sudah
  di `docs/kanban.md` (butuh running-PnL & multi-position tracking yang
  belum ada sama sekali, beda kelas masalah dari regime/kNN).
- Backfill `open_interest`/perpanjangan histori OHLCV 2-3 tahun — sudah
  jadi item roadmap terpisah (P1/P2, `sonnet5-implementation-roadmap.md`),
  disebut di sini sebagai dependency, bukan diambil alih.

## 9. Referensi

`docs/prd.md` §3.1/§6 (Layer 3, Fase 2) — spec target. `docs/kanban.md`
— catatan "belum ada desain sama sekali" yang memicu brief ini.
`gated_campaign.py` — infrastruktur causal-regime & harness promosi yang
di-reuse. `fit_weights.py` — corpus/feature-vector/adoption-gate yang
di-reuse untuk kNN. `derivatives_context.py` — OI-fuel sebagai konfirmasi
sekunder. `docs/shadow-simulator-brief.md` §5 — preseden cold-start ≥50
pasang & prinsip "ML tidak menentukan leverage maksimal". `CLAUDE.md` —
lesson `ConfluenceWeights` anti-prediktif yang jadi alasan kedua gate ini
wajib lolos walk-forward dulu sebelum live, bukan diasumsikan benar dari
desain di atas kertas.
