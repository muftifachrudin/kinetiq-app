# Context Brief: fib_gann_timing — untuk disinkronkan ke sesi Claude Code (kinetiq-app)

Ini hasil diskusi arsitektur di luar sesi Claude Code, khusus soal `fib_gann_timing` skill dan validation harness-nya. Tolong pahami ini sebagai konteks tambahan yang align dengan PRD, bukan pengganti PRD.

## Ringkasan Status Konfirmasi (per 2 Juli 2026)

Ini rekap dari 4 pertanyaan klarifikasi yang diajukan sesi Claude Code sebelumnya, dikonfirmasi langsung ke founder termasuk verifikasi via screenshot chart & settings TradingView:

| # | Topik | Status | Ringkasan |
|---|---|---|---|
| 1 | Swing high/low detection | **RESOLVED** | ZigZag % / ATR-based, threshold 1.5–2x ATR(14) sbg starting point (lihat bag. 3) |
| 2 | Level Fibonacci | **RESOLVED** | Modifikasi personal, bukan standar textbook — set lebih rapat (lihat bag. 2a) |
| 3a | Gann Fan — angle set | **RESOLVED** | Full 9 angle standar, semua aktif (lihat bag. 2b) |
| 3b | Gann Fan — kalibrasi price-per-time | **RESOLVED & VALIDASI VISUAL DONE (3 Juli 2026)** | Opsi 1: fixed reference scale dari swing basis pivot (`swing_range / swing_duration_bars`) — matched ke koordinat exact TradingView founder (lihat bag. 2c) |
| — | Market structure (BOS/CHoCH) | **RESOLVED (2 Juli 2026)** | Opsi (b): skill terpisah `market_structure.py`, plug ke `score_confluence()` lewat slot ala `regime_alignment` — bukan bagian tak terpisahkan dari `fib_gann_timing.py` (lihat bag. 2d) |
| 4 | Multi-timeframe confluence & bobot | **RESOLVED** | Weekly→Daily→4h→1h, bobot besar→kecil, sesuai draft PRD tanpa perubahan (lihat bag. 2e) |
| — | TP/SL, R:R gate, labeling | **SPEC BARU — siap implementasi** | SL struktural + tiered TP dari extension confluence + R:R gate ≥1.5 + triple-barrier labeling (lihat bag. 5) — klaim "reuse pipeline MARKOVIZ" di 5d **sudah diverifikasi & ternyata TIDAK bisa langsung di-reuse**, lihat catatan di 5d |
| — | Posisi fib_gann_timing dlm sistem | **OPEN — keputusan arsitektur** | Standalone validation dulu vs langsung jadi input graph (lihat bag. 1) |

**Untuk Claude Code**: semua baris RESOLVED + bag. 5 (spec TP/SL) bisa langsung dipakai sebagai spesifikasi round #2 `fib_gann_timing.py` tanpa perlu tanya ulang founder — termasuk Gann Fan yang sebelumnya di-skip (kalibrasi sudah diputuskan, lihat 2c). 1 baris "OPEN" tersisa (posisi `fib_gann_timing` dlm sistem, bag. 1) masih butuh keputusan eksplisit — jangan diasumsikan sendiri, tandai sebagai TODO di kode kalau menyentuh area itu.

## 1. Status keputusan: posisi fib_gann_timing MASIH EKSPLORASI

Belum diputuskan final apakah fib_gann_timing akan jadi:
- **(A)** Input skill ke `portfolio_rebalance_graph` — sesuai desain PRD Section B.6 (entry-timing gate + expected_return_component)
- **(B)** Agent/strategi independen yang divalidasi head-to-head vs MARKOVIZ V5 dulu, baru dipromosikan ke (A) kalau terbukti

**Keputusan sementara: bangun (B) dulu sebagai validation harness terpisah** — supaya performa fib_gann bisa diisolasi dan diukur tanpa tercampur noise dari portfolio optimizer. Begitu ada bukti walk-forward yang konsisten (lihat kriteria promosi di bagian 7), baru integrasi ke jalur (A) sesuai PRD.

Harness ini **tidak boleh** ditaruh di `agent-orchestrator/graphs/` — taruh di `agent-orchestrator/validation/` sebagai module terpisah yang reuse data layer, supaya tidak ada temptation untuk langsung nyambung ke Markowitz graph sebelum tervalidasi.

## 2a. Level Fibonacci — modifikasi personal (BUKAN standar generik)

Dikonfirmasi dari chart trading founder langsung (BTCUSD 4h), set yang dipakai lebih rapat dari standar:

**Retracement:** `0.382, 0.5, 0.618, 0.786, 0.886`
**Extension:** `1.13, 1.272, 1.414, 1.618, 2, 2.272, 2.618`

Beda dari standar textbook (0.236/0.382/0.5/0.618/0.786 + ext 1.272/1.618) di dua tempat:
- Ada `0.886` di retracement — level tambahan antara 0.786 dan swing point, dipakai sebagai zona konfirmasi lanjutan kalau 0.786 tertembus tapi belum invalid.
- Ada `1.13, 1.414, 2, 2.272` di extension — set lebih rapat khususnya di zona 0.786–1.13 dan 1.272–2.272, kemungkinan dipakai untuk presisi target/invalidation yang lebih granular dibanding jarak standar 1.272→1.618.

**Implikasi untuk `fib_gann_timing.py`**: jangan hardcode array level ke 4-5 angka standar. Definisikan sebagai config list per-instrumen yang bisa di-extend, default-nya pakai set founder di atas — bukan textbook generik.

## 2b. Gann Fan — full 9 angle standar, dikonfirmasi dari settings TradingView

**CONFIRMED** (dari screenshot settings Gann Fan TradingView founder, semua checkbox aktif): full 9 angle standar teori Gann dipakai sekaligus dari satu pivot yang sama:

```
1/8, 1/4, 1/3, 1/2, 1/1, 2/1, 3/1, 4/1, 8/1
```

**Implikasi**: desain awal PRD (B.6) yang bilang "proyeksi angle (1x1, 1x2, 2x1, dst)" sudah benar arahnya — pastikan implementasi generate **seluruh 9 angle sekaligus** dari satu pivot (bukan subset yang dipilih per config), dan confluence scoring (poin 4 di bawah) harus cek overlap fib level terhadap **semua 9 garis fan**, bukan cuma satu garis yang "dianggap default".

## 2c. Kalibrasi price-per-time-unit Gann — RESOLVED: Opsi 1 (fixed reference scale)

**Konteks**: founder pakai default TradingView (tidak pernah kalibrasi manual), yang menghitung rasio price/time dari scaling visual viewport chart — tidak portable ke backend headless karena tidak ada konsep "viewport" tanpa rendering.

**KEPUTUSAN (dikonfirmasi founder): Opsi 1 — fixed reference scale**, diturunkan dari swing yang sama yang jadi basis pivot fan:

```
price_per_time_unit = swing_price_range / swing_duration_in_bars
```

- `swing_price_range` dan `swing_duration_in_bars` diambil dari swing high-low yang ditentukan ZigZag/ATR detector (poin 3) — **satu sumber kebenaran**, bukan sistem kalibrasi terpisah.
- Angle 1x1 = 45° relatif terhadap displacement swing basis itu sendiri; angle lain (2/1, 1/2, dst) proporsional dari rasio itu.
- Otomatis adaptif per-instrumen (BTC vs altcoin beda skala harga, rasio tetap konsisten karena diturunkan dari swing masing-masing).

**Wajib ada langkah validasi visual setelah implementasi**: generate beberapa sample fan dari algoritma → founder eyeball-compare terhadap fan manual di TradingView untuk instrumen/timeframe yang sama. Kalau sudut jauh berbeda secara visual, tweak formula reference scale (mis. ganti basis ke ATR rolling N-period) — bukan berarti pendekatan fixed-scale-nya salah arah.

> **Validasi visual DONE (3 Juli 2026)**: founder gambar Gann Fan manual di
> TradingView (BTCUSDT perpetual, Binance, 1h) dan kasih koordinat exact
> dari tab "Coordinates" tool-nya sendiri (bukan estimasi visual/crosshair)
> — titik #1: harga 58,005.0 @ bar 127, titik #2: harga 60,908.9 @ bar 177
> (jarak 50 bar). Base rate 1x1 hasil formula `price_per_time_unit =
> swing_price_range / swing_duration_in_bars` = 58.078/bar, dan itu
> **matched langsung** terhadap definisi geometris TradingView sendiri
> (garis 1x1 = garis lurus antara 2 titik itu, jadi rate-nya memang
> harus persis segitu — bukan sesuatu yang perlu di-fit/didekati).
>
> **1 kesalahan verifikasi ketemu & diperbaiki di proses ini**: sempat ada
> percobaan cross-check ke garis "putih" di chart yang dikira 1x1, hasilnya
> meleset ~2x dari hitungan formula — investigasi lanjut (founder cek tab
> "Style" tool Gann Fan-nya) ketahuan garis putih itu **parallel channel**
> (tool gambar terpisah, gak ada hubungannya sama Gann Fan sama sekali),
> warna 1x1 yang benar itu **cyan**. Selisih 2x itu murni salah baca garis,
> BUKAN bug kalibrasi — begitu dibandingin ke garis & koordinat yang benar,
> cocok. Pelajaran buat validasi berikutnya: selalu cek warna garis di tab
> Style Gann Fan tool dulu sebelum baca angka dari chart, jangan asumsi
> dari posisi visual "garis tengah" doang.
>
> **Kalibrasi Opsi 1 sekarang resmi CONFIRMED, bukan lagi belum-tervalidasi**
> — boleh diandalkan di kode tanpa disclaimer "belum divalidasi" lagi.
>
> **Validasi ke-2 (sama hari, 3 Juli 2026) — kasus downtrend**: founder
> kasih 1 contoh fan lagi, kali ini inverse (HIGH ke bawah, timeframe 4h),
> koordinat exact dari tool: titik #1 harga 67,284.8 @ bar 197, titik #2
> harga 62,233.3 @ bar 214 (jarak 17 bar). Rate hasil formula =
> 297.147/bar, matched persis lagi ke definisi geometris TradingView.
>
> **Temuan penting dari contoh ke-2 ini**: di KEDUA contoh (uptrend & downtrend),
> titik origin (yg founder klik pertama, tempat semua garis fan konvergen)
> itu **kronologis LEBIH AWAL** dari titik kedua (yg cuma dipakai nentuin
> slope) — pola manual founder emang gitu (pilih swing signifikan yg lama,
> baru pilih titik lain yg lebih baru buat nentuin sudut). Ini KEBALIKAN
> dari asumsi awal `gann_base_rate()`, yg didesain buat kasus live/backtest
> signal (`pivot` = swing PALING BARU dari `detect_swings()`, `basis_leg_start`
> = swing SEBELUMnya, jadi basis SELALU lebih awal dari pivot). Kode
> awalnya nolak (`ValueError`) kalau urutan dibalik seperti pola manual
> founder. **Sudah di-fix**: `gann_base_rate()` sekarang terima basis_leg_start
> di kedua sisi kronologis (cuma nolak kalau index-nya sama persis, gak ada
> jarak buat dihitung rate-nya) — dites eksplisit thd 2 contoh koordinat
> exact founder ini + kasus lama (basis sblm pivot) tetap jalan gak
> keregresi. Detail di `docs/prd.md`.
>
> **Item baru masuk backlog dari sesi validasi ini (bukan diminta sekarang,
> dicatat aja)**: founder juga pakai **parallel channel** (tool terpisah
> dari Gann Fan) di chart-nya bareng fib+gann+BOS/CHoCH — belum ada scope
> resminya di PRD B.6 sama sekali (beda dari BOS/CHoCH yang minimal udah
> disebut brief). Kandidat jadi skill baru (`market_channel.py`?) kalau
> nanti mau diformalisasi juga — belum diputuskan, jangan diimplementasi
> dulu sebelum dikonfirmasi scope-nya sama founder, sama persis pola BOS/
> CHoCH sebelum diputuskan di bag. 2d.

## 2d. Market structure (BOS/CHoCH) — layer tambahan yang belum ada di PRD

Chart founder menunjukkan label eksplisit `BOS` (Break of Structure) dan `CHoCH` (Change of Character) — ini konsep Smart Money Concept (SMC), dipakai **bersamaan** dengan fib+gann, bukan strategi terpisah. Berdasarkan posisi label di chart, pola pemakaiannya: CHoCH menandai potensi pivot baru terbentuk (structure shift), BOS mengkonfirmasi kelanjutan arah setelah shift itu — kombinasi keduanya kemungkinan jadi **trigger tambahan** untuk kapan swing point dianggap valid untuk dipakai sebagai basis fib/gann, di luar threshold ATR yang dibahas di poin 3.

**Ini bukan scope resmi PRD saat ini** (B.6 cuma sebut fib+gann+multi-timeframe confluence). Perlu dikonfirmasi eksplisit ke founder: apakah BOS/CHoCH ini (a) bagian tak terpisahkan dari `fib_gann_timing` yang harus diformalisasi bareng, atau (b) skill terpisah (`skills/strategy/market_structure.py`) yang jadi salah satu input confluence, sama seperti `market_regime.py`. **Belum diputuskan — jangan diimplementasi dulu sebelum founder confirm arahnya**, tapi wajib dicatat sebagai gap supaya tidak tertinggal dari formalisasi.

> **Resolved (2 Juli 2026)**: founder pilih opsi **(b) skill terpisah**.
> `skills/strategy/market_structure.py` sekarang ada — `trend_bias()` baca
> higher-high/higher-low (atau lower-high/lower-low) dari 2 swing terakhir
> tiap tipe hasil `detect_swings()`, `detect_structure_event()` cek apakah
> `reference_price` break di atas swing high terakhir atau di bawah swing
> low terakhir dan label BOS (searah trend yang udah established) vs CHoCH
> (berlawanan, atau trend belum established) sesuai definisi di paragraf
> di atas ("CHoCH menandai shift, BOS mengkonfirmasi kelanjutan"). Output-
> nya plug ke `fib_gann_timing.score_confluence()` lewat
> `structure_alignment_score()`, slot yang sama polanya kayak
> `regime_alignment` (skor 0-1, penalti berat bukan block total kalau
> berlawanan arah trade) — BUKAN jadi trigger validitas swing point di
> `detect_swings()` (opsi (a) yang gak dipilih). Detail implementasi &
> verifikasi data real di `docs/prd.md`.

## 2e. Multi-timeframe confluence — Weekly/Daily/4h/1h, bobot besar→kecil (CONFIRMED, match draft PRD)

**CONFIRMED dari founder**: set timeframe dan urutan bobot yang ada di draft PRD (B.6) **sudah tepat**, tidak perlu disesuaikan:

```
Weekly (bobot tertinggi) → Daily → 4h → 1h (bobot terendah)
```

Weekly paling berpengaruh terhadap confluence score, turun proporsional ke Daily/4h/1h. Beda dari 4 poin sebelumnya (2a-2d) yang butuh koreksi dari asumsi generik, poin ini **tidak ada gap** — implementasi bisa langsung ikut spesifikasi PRD B.6 apa adanya untuk bagian ini.

## 3. Swing detection: ZigZag % / ATR-based (final)

Bukan Fractal N-bar, bukan manual visual. Alasan:
- Fractal N-bar (fixed 5-bar) itu predictable — level fib/gann yang dihasilkan gampang di-hunt karena semua orang pakai setting sama.
- ATR-based ZigZag proporsional terhadap volatilitas aktual, nyambung ke regime classifier (RISK_ON/OFF/NEUTRAL/FREEZE) yang sudah ada di macro sidecar.
- Threshold rekomendasi: **1.5–2x ATR(14)** sebagai starting point, di-tune lewat kalibrasi `trader_profile` (agreement rate vs `trade_annotation`).
- Tambahan: pertimbangkan **wick-rejection filter** — swing point yang baru saja di-sweep (rejection wick signifikan) dapat bonus confidence, karena mengindikasikan stop-hunt sudah selesai duluan sebelum reversal.
- Swing detection HARUS strict no-lookahead: hanya boleh pakai data sampai `as_of` timestamp, termasuk saat backtest.

## 4. Confidence/confluence scoring — komponen tambahan untuk B.6

PRD sudah punya multi-timeframe confluence score (0-100). Usulan komponen granular di dalamnya:

```
confidence = w1*swing_quality + w2*fib_gann_confluence + w3*regime_alignment
           + w4*volume_confirmation + w5*wick_rejection_score
```

- `swing_quality`: rasio displacement vs ATR + recency swing.
- `fib_gann_confluence`: overlap antara level fib dan gann angle price, dinormalisasi terhadap ATR current. Kalau overlap > 0.5x ATR, JANGAN dipaksa jadi confluence — itu kebetulan lewat area sama, bukan genuine confluence.
- `regime_alignment`: sinyal LONG saat RISK_OFF/FREEZE dipenalti berat (bukan di-block total).
- `volume_confirmation`: displacement candle pembentuk swing harus di atas rolling average volume.
- `wick_rejection_score`: lihat poin 3.

Bobot w1–w5 JANGAN di-hardcode dari feeling — fit pakai logistic regression terhadap outcome historis, reuse pipeline yang sama dengan kalibrasi `trader_profile` (B.6b).

## 5. TP/SL & labeling — spesifikasi untuk round #2 (`fib_gann_timing.py`)

Spesifikasi exit management + kalibrasi label, melengkapi confluence scoring di poin 4. Prinsip dasar: **target optimasi adalah expectancy per trade (PF net), BUKAN winrate** — winrate bisa dinaikkan artifisial dengan TP kecil/SL besar dan itu justru merusak expectancy.

### 5a. SL — struktural, bukan angka fixed

- SL ditempatkan **di balik swing point yang jadi basis fib** (invalidation struktural: kalau swing patah, premis trade mati) + **buffer berbasis ATR** (mis. 0.25–0.5x ATR(14)) supaya tidak persis di level obvious yang rawan wick hunt — konsisten dengan wick-rejection filter di poin 3.
- SL price harus deterministic dari swing yang sama yang dipakai fib/gann — satu sumber kebenaran, bukan parameter terpisah.

### 5b. TP — tiered dari level extension founder, confluence-aware

- TP BUKAN satu angka: **tiered exit** memakai level extension set founder (`1.13, 1.272, 1.414, 1.618, 2, 2.272, 2.618` — lihat 2a):
  - **TP1**: extension pertama searah trade yang **confluence dengan salah satu garis Gann fan** (bukan sekadar extension terdekat) → partial exit (porsi configurable, default mis. 50%).
  - **Sisa posisi**: trail ke level extension+confluence berikutnya, SL sisa posisi dinaikkan ke breakeven setelah TP1 tercapai.
- Definisi "confluence" untuk TP memakai kriteria yang sama dengan poin 4 (overlap fib-vs-gann ≤ 0.5x ATR).

### 5c. R:R gate — filter wajib sebelum sinyal valid

- Sinyal HANYA valid jika `(entry → TP1) / (entry → SL) ≥ min_rr_threshold` (default **1.5**, configurable & ikut dikalibrasi).
- Sinyal dengan confluence score tinggi tapi struktur R:R jelek = **skip, bukan diturunkan bobotnya**. Ini gate binary, terpisah dari confidence scoring.
- Gate ini masuk SEBELUM sinyal dipublish/dicatat — sinyal yang gagal gate tetap boleh di-log internal (untuk kalibrasi), tapi tidak pernah jadi output.

### 5d. Triple-barrier labeling — untuk kalibrasi bobot & trader_profile

Untuk fitting bobot confluence (w1–w5 di poin 4) dan kalibrasi `trader_profile` (PRD B.6b), label outcome tiap sinyal historis memakai **triple-barrier method** (López de Prado), BUKAN label naive "harga naik = win":

- **Upper barrier** = TP1 (dari 5b), **lower barrier** = SL (dari 5a), **vertical barrier** = time-out (max holding period, mis. N candle pada timeframe sinyal — parameter kalibrasi).
- Label: `+1` (TP tersentuh dulu), `-1` (SL tersentuh dulu), `0`/return-at-timeout (vertical barrier duluan).
- Kompatibel langsung dengan pipeline logistic regression meta-model MARKOVIZ yang sudah ada — **reuse pipeline itu**, jangan tulis ulang dari nol.

> **Verifikasi Claude Code (2 Juli 2026)**: klaim di atas dicek langsung ke `ai-perp-bot-core`
> (`META-MODEL-GUIDE.md` + cross-check kode asli `src/meta-score.ts`, bukan cuma dokumentasi) —
> hasilnya **tidak bisa langsung "reuse pipeline itu" seperti disebut di atas**:
> - Model produksi MARKOVIZ sekarang **GBM (Gradient Boosted Trees)**, bukan logistic regression
>   murni — LogReg cuma fallback kalau sampel training <40. Bukan mismatch besar konsepnya, tapi
>   klaim "logistic regression meta-model" di atas sudah gak match kondisi kode terkini.
> - Skema label MARKOVIZ itu **binary sederhana** (`label: 0|1` WIN/LOSS dari P&L trade real +
>   shadow-labeling utk sinyal yang di-skip/orphaned), **bukan triple-barrier**. Ini BUKAN masalah
>   buat spec 5d di atas — triple-barrier fib_gann tetap lebih tepat dipakai — tapi berarti dua
>   metode ini punya filosofi label yang beda pas nanti dibandingkan hasilnya.
> - 19 fitur GBM MARKOVIZ (7-pillar signal engine + macro + session context) **tidak overlap sama
>   sekali** dengan fitur fib_gann (swing quality, wick rejection, fib/gann confluence, dst) — beda
>   domain sinyal total.
> - Threshold (`LIVE_META_MIN_PROBA`) dikalibrasi manual staged rollout (0.55 → 0.52 kalau win rate
>   tetap bagus), bukan hasil optimasi statistik — jadi pola manual-staged ini yang layak ditiru
>   buat kalibrasi R:R gate di 5c, bukan angkanya sendiri.
>
> **Kesimpulan praktis**: triple-barrier labeling di bagian ini **harus ditulis dari nol pakai
> scikit-learn** (beda bahasa & beda fitur dari MARKOVIZ, jadi memang bukan soal port kode) — yang
> layak ditiru dari MARKOVIZ cuma pola metodologisnya: shadow-labeling utk sinyal yang gak
> dieksekusi, evaluasi pakai cross-validation + AUC/Brier/accuracy, dan kalibrasi threshold
> bertahap manual. Detail lengkap di `docs/prd.md` bagian status Fase 2.

- Barrier check HARUS pakai data intrabar yang lebih granular dari timeframe sinyal (mis. sinyal 4h → cek barrier pakai 1h/15m) supaya urutan TP-vs-SL-tersentuh-duluan akurat, bukan asumsi dari OHLC candle sinyal saja. Kalau data granular tidak tersedia, pakai aturan konservatif: kalau dalam satu candle TP dan SL dua-duanya tersentuh, **hitung sebagai SL** (worst-case assumption).

### 5e. Kecepatan sinyal — definisi realistis

- "Cepat" = deteksi swing baru + confluence check + R:R gate selesai **dalam satu candle close** pada timeframe sinyal. Closed-candle only, no repaint (konsisten poin 3).
- JANGAN mengejar sub-menit/tick untuk MVP — metode fib+gann founder beroperasi di 1h-4h-Daily-Weekly (lihat 2e), latency detik setelah candle close sudah memadai dan infra cost-nya proporsional.

## 6. Validation harness — struktur

```
apps/products/trading/agent-orchestrator/
  validation/
    fib_gann_backtest/
      data_loader.py       # reuse ingestion connector, no live calls
      walk_forward.py      # (deprecated di sini, pindah ke packages/backtest-core)
      signal_runner.py     # panggil fib_gann_timing.py murni, no graph, no LangGraph
      trade_simulator.py   # funding-aware trade simulation
      metrics.py           # PF/Sharpe/DD funding-aware, regime-segmented
      report.py            # dump ke docs/validation-results/ (JSON/markdown dulu, bukan tabel DB baru)
    configs/
      walk_forward_windows.yaml
    run_validation.py      # CLI entrypoint, wajib support --dry-run
```

### Shared walk-forward util (PENTING — cegah duplikasi dengan MARKOVIZ V5)

Pindahkan window generator ke `packages/backtest-core/src/kinetiq_backtest/` (sejajar `packages/db`), supaya MARKOVIZ V5 dan fib_gann_backtest pakai generator + config **yang identik**. Jangan biarkan dua strategi punya window logic yang beda diam-diam — itu bikin komparasi hasil tidak valid.

- `types.py`: `WalkForwardWindow` (frozen dataclass), `WindowMode` (ROLLING/ANCHORED)
- `windowing.py`: `generate_windows()` — default mode ANCHORED (expanding train), tapi **cek dulu config MARKOVIZ V5 existing sebelum nentuin default final**, supaya migrasi tidak diam-diam mengubah hasil OOS yang sudah ada
- `validators.py`: `validate_window_set()` — cek no-leak (test_start > train_end), embargo gap terpenuhi, no overlap antar test set, no duplicate window_id
- Config walk-forward (`train_months`, `test_months`, `embargo_days`, `mode`) di satu file YAML, dipakai kedua caller

**Migration path untuk MARKOVIZ V5** (jangan langsung replace):
1. Bangun `packages/backtest-core`, tulis test yang assert output match hasil window MARKOVIZ existing (dengan config yang sama)
2. Swap import MARKOVIZ V5 ke package baru, jalankan regression test — pastikan PF/Sharpe per window TIDAK berubah
3. Baru fib_gann_backtest pakai package ini dari awal (tidak perlu migrasi karena baru)

### Metrics — funding-aware (WAJIB, bukan opsional)

Semua PF/Sharpe/drawdown dihitung dari **net PnL setelah funding cost**, bukan raw price PnL:
- Funding accumulation snapshot-based (tiap periode funding aktual dilewati posisi, bukan prorata continuous)
- Selalu laporkan PF gross vs PF net berdampingan — gap besar = strategi terlalu bergantung raw momentum yang dimakan biaya holding
- Sharpe di-annualize dari rata-rata trade frequency (holding period aktual), BUKAN asumsi 252 trading days — crypto perp 24/7 dengan holding period tidak seragam
- Breakdown metrics per regime (RISK_ON/OFF/NEUTRAL/FREEZE) — insight penting apakah fib_gann konsisten profitable atau cuma menang di regime tertentu

**Action item cross-check**: kalau formula PF/Sharpe MARKOVIZ V5 saat ini belum funding-aware seperti di atas, itu kemungkinan salah satu sumber OOS PF < 1.0 yang belum ketauan — worth diinvestigasi terpisah dari masalah signal quality.

## 7. Kriteria promosi dari validation harness → jalur PRD (A)

Tentukan threshold SEBELUM mulai run backtest, supaya keputusan objektif bukan feeling:
- PF net > 1.3 konsisten di minimal 4 dari 6 window test
- Agreement rate > 60% terhadap `trade_annotation` manual (dari B.6b)

Kalau tidak tercapai, hasil tetap valuable sebagai input kalibrasi ulang `trader_profile` params — bukan berarti gagal total.

## 8. Unit test coverage untuk windowing (edge cases wajib ditest)

- DST boundary — paksa semua datetime UTC-aware, tolak input naive datetime secara eksplisit
- Bulan dengan panjang berbeda (`relativedelta` dari tanggal 29-31)
- Leap year (window yang nyebrang 29 Feb)
- Range terlalu pendek — harus return list kosong dengan jelas, bukan infinite loop
- `step_months != test_months` (overlapping windows) — pastikan intentional, validator punya flag `allow_test_overlap`
- Regression test: commit config MARKOVIZ V5 saat ini, assert output window generator baru identik dengan versi lama
