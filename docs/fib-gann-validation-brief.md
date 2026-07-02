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

> **Verifikasi Claude Code (3 Juli 2026)**: cek langsung ke tab "Coordinates"
> + "Style" tool Fib Retracement TradingView founder (BTCUSDT 1h) —
> **nemuin 2 hal yang perlu dikoreksi dari spek di atas**:
> - **Level `3.618` ternyata AKTIF di tool founder** (extension), gak ada
>   di daftar bag. ini maupun di `DEFAULT_FIB_EXTENSION_LEVELS` sebelum
>   ini — udah ditambahin.
> - **Formula `compute_fib_levels()` ternyata TERBALIK ARAHNYA** — sblm ini
>   fungsi hitung `swing_high - level*leg` (0%=high, 100%=low, extension
>   proyeksi ke BAWAH swing_low). Koordinat exact tool founder (titik #1
>   60,919.9 @ bar 160, titik #2 58,029.2 @ bar 328) + 9 harga level yg
>   ke-label langsung di chart, di-fit least-squares ke `swing_low +
>   level*leg` dgn **R²=1.000000** — jadi arah yg BENAR itu 0%=swing_low,
>   100%=swing_high, extension proyeksi ke ATAS swing_high. Formula sudah
>   di-flip. Ini juga ngejelasin kenapa `compute_take_profit_levels()`
>   (spec bag. 5b) sebelumnya HARUS nulis formula extension sendiri
>   terpisah dari `compute_fib_levels()` buat kasus LONG — sekarang
>   `compute_fib_levels()` yg udah bener malah otomatis match persis sama
>   cabang LONG itu. **Cabang SHORT `compute_take_profit_levels()` (extension
>   ke BAWAH swing_low) masih BELUM tervalidasi** thd chart real — itu
>   asumsi cerminan buat simetri, bukan hasil verifikasi, ditandai jelas di
>   docstring kode. Detail lengkap di `docs/prd.md`.

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
> **Validasi ke-3 (sama hari, 3 Juli 2026) — instrumen beda (SOLUSDT, 1h)**:
> koordinat exact dari tool: titik #1 harga 64.03 @ bar 127, titik #2 harga
> 73.84 @ bar 157 (jarak 30 bar). Rate hasil formula = 0.327/bar, matched
> lagi. Ini konfirmasi tambahan yang penting krn skala harga SOL (~$60-90)
> jauh beda dari BTC (~$58k-67k) — bukti klaim "otomatis adaptif
> per-instrumen" di formula ini beneran kepegang, bukan kebetulan cocok
> khusus buat BTC doang. 3 dari 3 contoh koordinat exact yg dites (2
> instrumen, 2 arah trend, 2 timeframe beda: 1h & 4h) semuanya matched
> tanpa exception.
>
> **Item baru masuk backlog dari sesi validasi ini (bukan diminta sekarang,
> dicatat aja)**: founder juga pakai **parallel channel** (tool terpisah
> dari Gann Fan) di chart-nya bareng fib+gann+BOS/CHoCH — belum ada scope
> resminya di PRD B.6 sama sekali (beda dari BOS/CHoCH yang minimal udah
> disebut brief). Kandidat jadi skill baru (`market_channel.py`?) kalau
> nanti mau diformalisasi juga — belum diputuskan, jangan diimplementasi
> dulu sebelum dikonfirmasi scope-nya sama founder, sama persis pola BOS/
> CHoCH sebelum diputuskan di bag. 2d.
>
> **Update (3 Juli 2026)**: ditanya scope-nya ke founder. Fungsinya buat
> nentuin struktur market (upper channel vs down channel), TAPI founder
> catat sendiri sering ada **fakeout** — harga tembus keluar channel terus
> balik lagi ke dalam — yang bikin rule breakout-vs-bounce sederhana gak
> reliable dipakai langsung. **KEPUTUSAN founder: SKIP dulu**, jangan
> diimplementasi sekarang — ditambahin nanti sbg skill terpisah pas MVP
> udah jalan & akurasi confluence yg ada (fib+gann+BOS/CHoCH) udah oke,
> baru dipakai buat nguatin agent lebih lanjut. Bukan ditolak permanen,
> cuma sengaja dijadwalkan setelah MVP, bukan bagian dari scope sekarang.

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
      data_loader.py       # reuse ingestion connector, no live calls -- DONE (3 Juli 2026)
      walk_forward.py      # (deprecated di sini, pindah ke packages/backtest-core) -- DONE, sudah di packages/backtest-core
      signal_runner.py     # panggil fib_gann_timing.py murni, no graph, no LangGraph -- DONE (3 Juli 2026), single-timeframe dulu
      trade_simulator.py   # funding-aware trade simulation -- BELUM
      metrics.py           # PF/Sharpe/DD funding-aware, regime-segmented -- BELUM
      report.py            # dump ke docs/validation-results/ (JSON/markdown dulu, bukan tabel DB baru) -- BELUM
    configs/
      walk_forward_windows.yaml -- BELUM
    run_validation.py      # CLI entrypoint, wajib support --dry-run -- BELUM
```

Status detail (bug nyata ketemu & di-fix pas verifikasi thd data production asli, termasuk kasus signal_runner ngasih R:R palsu bagus krn entry udah lewat level SL) di `docs/prd.md` bagian status Fase 2.

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

### 6a. Level strength scoring — teori founder (3 Juli 2026), touch tracker

> **Verifikasi Claude Code**: founder mengajukan teori tambahan — kekuatan
> sebuah level fib/gann sebagai support/resistance itu tidak tetap, dan
> bisa dilabeli dari histori "sentuhan" harga terhadapnya:
> - Ratio 0.618 (dan pasangan extension-nya 1.618, golden ratio) adalah
>   level S/R fib terkuat — lebih kuat dari ratio lain.
> - Makin besar timeframe tempat level itu digambar, makin kuat.
> - Makin jarang level itu disentuh ("liquidity magnet" — level virgin
>   menarik & menahan harga), makin kuat. Makin sering disentuh, makin
>   lemah.
> - Setiap sentuhan bisa dilabeli: bounce (harga memantul/reversal — S/R
>   bertahan) atau reject/break (harga tembus).
>
> Dibangun 2 bagian berurutan (deterministic dulu, ML-fit belakangan —
> pola yang sama dengan `ConfluenceWeights` di `fib_gann_timing.py`, yang
> juga masih formula starting-point, belum di-fit ke data trade beneran):
>
> **Part #1 (DONE, 3 Juli 2026)** — `skills/strategy/level_strength.py`:
> - `detect_level_touches()`: jalan sepanjang candle series, deteksi tiap
>   bar yang harganya benar-benar menyentuh sebuah level
>   (`candle.low <= level <= candle.high`), lalu klasifikasi outcome-nya
>   dengan mengintip sampai `max_resolution_bars` (default 10) candle ke
>   depan — BOUNCE kalau close balik menjauh dari level lebih dari
>   `outcome_atr_buffer_multiplier * ATR` (default 0.25×), BREAK kalau
>   close tembus lebih dari buffer itu ke arah yang sama, CENSORED kalau
>   ambigu (termasuk kasus data historis habis sebelum window resolusi
>   selesai — right-censored, sama seperti `label_triple_barrier()`).
>   `level_price_at` berupa callable (bukan float tetap) supaya secara
>   arsitektur bisa dipakai juga untuk garis Gann yang bergerak tiap bar —
>   **tapi ini belum diverifikasi/dilatih terhadap garis Gann beneran**,
>   baru terhadap level fib retracement/extension statis.
> - `level_strength_score()`: menggabungkan touch history satu level jadi
>   satu angka deterministic — `timeframe_weight × ratio_weight ×
>   freshness × broken_penalty`, di mana `ratio_weight` = 1.5× kalau
>   ratio-nya 0.618/1.618 (golden ratio, sesuai klaim founder) dan 1.0×
>   untuk ratio lain; `freshness` = `1 / (jumlah sentuhan sebelumnya + 1)`
>   (makin jarang disentuh, makin tinggi — mengoperasionalkan "magnet");
>   `broken_penalty` = 0.2× kalau ADA sentuhan sebelumnya (bukan sentuhan
>   yang sedang dinilai) yang resolve jadi BREAK — sekali level itu
>   ditembus bersih, dianggap invalidated sebagai S/R meski masih fresh.
> - **Belum di-wire ke `fib_gann_confluence_score()` / `score_confluence()`
>   di `fib_gann_timing.py`** — 5 faktor `ConfluenceWeights` yang ada
>   sekarang sudah jumlah tetap 1.0, cara sebuah faktor ke-6 masuk ke
>   formula itu (bobot baru? ubah `fib_gann_confluence_score` sendiri?
>   pendekatan lain?) adalah keputusan desain terpisah untuk round
>   berikutnya, tidak diasumsikan di sini.
> - Diverifikasi terhadap data production asli (BTC/USDT 1h, pivot HIGH
>   idx=48 @ 60666.6, basis LOW idx=45 @ 58988.0): level
>   `retracement_0.618` sentuhan pertama skor 0.1500 — persis 1.5× skor
>   sentuhan pertama level non-golden-ratio lain (0.1000), konsisten
>   dengan klaim founder. Level yang sudah BREAK sekali (mis.
>   `retracement_0.382` sentuhan #1 di idx 58) langsung menjatuhkan skor
>   sentuhan berikutnya sampai 0.2× lipat lebih rendah dari yang seharusnya
>   (0.0100 vs ~0.0500 tanpa penalty). Level extension TIDAK tersentuh
>   sama sekali di window 100-candle ini (harga tidak pernah extend di
>   atas swing_high) — jadi touch-tracking untuk extension levels belum
>   punya bukti data real, meski code path-nya identik dengan retracement.
> - 17 test baru (`tests/test_level_strength.py`), total suite jadi 116
>   test, semua passing, ruff clean.
>
> **Part #2 (BELUM)** — fitting bobot (`GOLDEN_RATIO_BASE_WEIGHT`,
> `ALREADY_BROKEN_PENALTY`, dst.) beneran pakai logistic regression atau
> metode serupa terhadap data trade teranotasi asli, sama seperti
> `ConfluenceWeights` — diblokir oleh hal yang sama: belum ada data
> `trade_annotation` (PRD B.6b) yang cukup. Wiring ke confluence scoring
> juga masuk Part #2, bukan Part #1.

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

## 9. Roadmap "prediksi perjalanan trade" — arah, target, durasi, reversal, sesi, fuel (3 Juli 2026)

> **Verifikasi Claude Code**: founder minta agent trading punya kemampuan
> lebih dari sekadar "sinyal masuk" — harus bisa memprediksi ke mana harga
> akan pergi (TP, seberapa jauh dlm %), kalau gagal (SL) apakah harga
> balik ke rumah (retrace ke entry) atau malah lanjut jadi tujuan baru
> arah berlawanan (reversal), berapa lama itu semua bakal makan waktu, dan
> pola behavior trader per jam (mis. sesi Asia sering long) yg
> divisualisasikan sbg peta/chart — "bahan bakar"-nya volume & open
> interest. Dipecah jadi 4 kapabilitas konkret, dipetakan ke yg udah ada
> vs belum:
>
> 1. **Prediksi durasi (time-to-target)** — **DIPILIH founder sbg
>    prioritas round berikutnya.** Datanya udah ada di
>    `label_triple_barrier()`'s `bars_held`/`exit_ts`, tinggal dibangun
>    agregator/prediktor: distribusi jumlah bar sampai TP/SL/timeout,
>    dikelompokkan per arah trade + skor confluence (+ nanti sesi jam,
>    kalau bag. 3 di bawah udah ada). BELUM dibangun — dijeda dulu atas
>    permintaan founder utk dokumentasi + riset CoinGlass ini duluan.
> 2. **Reversal vs continuation setelah SL** ("pulang" vs "tujuan baru
>    arah berlawanan") — classifier baru, manfaatin `market_structure.py`
>    CHoCH detector yg udah ada persis di titik SL. BELUM dibangun.
> 3. **Bias sesi jam (Asia/London/NY)** — perlu candle GRANULARITY
>    intraday (jam/menit) utk tagging sesi yg akurat. BELUM dibangun, DAN
>    **terblokir data** (lihat probe CoinGlass di bawah — Hobbyist cuma
>    kasih data harian, gak cukup granular utk analisis per-jam).
> 4. **Volume & Open Interest sbg "bahan bakar"** — belum di-wire ke
>    confluence scoring. Divalidasi arahnya via probe data real di bawah.

### Probe data real CoinGlass Hobbyist (3 Juli 2026) — `COINGLASS_API_KEY` sudah ada di env, `open-api-v4.coinglass.com` reachable dari sandbox Claude Code (beda dari `fapi.binance.com`/`console.neon.tech` yg diblokir)

Endpoint yg dicoba & hasilnya (semua `code: 0`, sukses) thd BTC, 90 hari terakhir:
- `futures/open-interest/aggregated-history` (interval `1d`) — OK
- `futures/price/history` (interval `1d`) — OK
- `futures/funding-rate/history` (interval `1d`) — OK
- `futures/liquidation/aggregated-history` (interval `1d`, wajib param `exchange_list`) — OK
- `futures/taker-buy-sell-volume/history` (interval `1d`, symbol format `BTCUSDT` bukan `BTC`) — OK
- `futures/liquidation/heatmap` — 404, endpoint gak ada/beda nama dari yg diasumsikan, belum diinvestigasi lanjut

**Konfirmasi langsung (bukan cuma baca ToS docs kayak riset PRD B.11 sebelumnya)**: request `interval=1h`/`15m` ke endpoint yg sama balikin data, TAPI granularity aslinya di plan Hobbyist tetap harian per dokumentasi CoinGlass sendiri — **belum dites eksplisit di sesi ini apakah `1h` benar2 granular jam-per-jam atau di-downsample diam2 ke harian**, jadi klaim "Hobbyist = daily-only" di B.11/tabel budget **masih berdiri sbg batasan yg harus diasumsikan berlaku** (bukan dikonfirmasi ulang lewat percobaan langsung interval jam) sampai ada verifikasi eksplisit — dicatat di sini biar gak diklaim "udah diverifikasi" padahal cuma daily endpoint yg beneran dicoba.

**Validasi teori "OI sbg bahan bakar" (kapabilitas #4 di atas) thd 89 hari data harian real BTC/USDT**:
| Kuadran (arah harga × arah OI) | n hari | rata² \|gerak harga\| |
|---|---|---|
| price↓ + OI↓ (long liquidation/capitulation) | 33 | 1.52% |
| price↑ + OI↑ (fresh longs — fuel confirmed) | 26 | 2.05% |
| price↑ + OI↓ (short covering — rally lemah) | 17 | 0.66% |
| price↓ + OI↑ (fresh shorts — fuel confirmed) | 13 | 1.64% |

Rata² gerak harga hari² yg OI-nya SEARAH sama harga (fuel confirmed, n=39): **1.91%** vs hari² yg OI-nya BERLAWANAN (no fuel, n=50): **1.22%**. **Arahnya konsisten sama teori** (hari fuel-confirmed gerak ~1.6x lebih jauh) — tapi ini cuma korelasi deskriptif sampel kecil (89 hari, 1 instrumen), BUKAN backtest prediktif, jadi belum bisa dianggap "tervalidasi" dlm arti yg sama kayak validasi Gann Fan/Fib (yg itu geometris exact, ini statistik noisy). Perlu sampel lebih besar + multi-instrumen sebelum dijadiin bobot confluence yg pasti.

**Liquidation cascade check** (5 hari long-liquidation terbesar dari 90 hari): SEMUA 5 hari itu closing harganya turun (range -0.41% s/d -6.53%) — konsisten sama pola "liquidation cascade" (posisi long yg ke-liquidasi paksa jual, dorong harga makin turun, konsisten sama konsep "magnet" level_strength.py: cluster leverage besar = level yg harga condong "ditarik" ke situ). Cuma 5 sampel, indikatif bukan konklusif.

**Kesimpulan praktis buat kapabilitas #4**: data OI/funding/liquidation/taker-flow harian dari CoinGlass Hobbyist SUDAH CUKUP buat mulai bangun "fuel confirmation" sbg confluence factor tambahan (deterministic dulu, sama pola `level_strength.py`) — gak perlu upgrade tier buat versi harian ini. Tapi kapabilitas #3 (bias sesi jam) tetap terblokir data granular, sesuai batasan yg udah dicatat di B.11 sblm ini.

**Reminder eksplisit (diminta founder)**: `level_strength.py` Part #2 (fitting bobot beneran via logistic regression + wiring ke `fib_gann_confluence_score()`/`score_confluence()`) **masih BELUM dikerjakan** — status tetap sama seperti bag. 6a, cuma dicatat ulang di sini biar gak kelewat pas lanjut ke kapabilitas baru manapun dari bag. ini.

## 10. Prinsip standing: gate keras vs faktor skor (cegah over-veto & overfit ke intuisi) — 3 Juli 2026

> **Verifikasi Claude Code**: founder angkat concern penting — makin banyak teori ditambah (golden ratio, level strength, OI fuel, bias sesi, reversal classifier, durasi, dst.), makin besar risiko sistem jadi susah ngasih sinyal sama sekali (over-veto), atau ke-fit ke intuisi/segelintir contoh chart daripada pola yg beneran general (overfitting). **Standing rule ini berlaku utk SEMUA kapabilitas baru dari bag. 9 dst., sama posisinya kayak pola "deterministic dulu, ML-fit belakangan" dari bag. 6a** — bukan cuma catatan sekali pakai.

**Dua risiko yg beda, jangan dicampur:**
1. **Over-veto** — tiap gate biner (wajib lolos, tolak total kalau gagal) yg ditumpuk MENGALIKAN reject rate. Dibuktikan konkret ke data real (BTC/USDT 1h, 100 candle, 3 Juli 2026): dari 70 kejadian sentuhan fib/gann (13 pivot beda), **cuma 1 gate** (R:R ≥ 1.5) udah nolak **96%**-nya (70 → 3 sinyal akhir). Nambah 2-3 gate keras baru dari teori baru manapun bisa dengan gampang bikin sinyal jadi NOL — bukan krn analisisnya salah, tapi krn aritmatika gate numpuk.
2. **Overfitting** — bukan masalah statistik dlm arti ketat SAAT INI (belum ada satupun angka di sistem yg beneran di-fit dari data — `GOLDEN_RATIO_BASE_WEIGHT=1.5`, `ALREADY_BROKEN_PENALTY=0.2`, `DEFAULT_MIN_RR_THRESHOLD`, `ConfluenceWeights` semuanya starting-point tebakan manusia, bukan hasil regresi). Risiko nyatanya adalah **"overfit ke intuisi"** — makin banyak konstanta hand-tuned ditambah tanpa validasi thd sampel besar, makin besar kemungkinan sistem cuma cocok ke chart yg pernah direview bareng, bukan pola yg general.

**Aturan desain (berlaku ke SEMUA faktor baru — level_strength, OI/volume fuel, bias sesi, reversal classifier, durasi, dst.):**
- **Gate keras (reject total) HANYA utk yg struktural invalid** — entry di sisi salah SL (`_entry_is_valid`), R:R di bawah threshold (`passes_risk_reward_gate`). Ini 2 gate yg ADA SEKARANG, jangan ditambah tanpa alasan struktural yg sama kuat.
- **Semua faktor baru masuk sbg kontributor skor tertimbang ke `confidence`** (pola yg sama kayak `ConfluenceWeights`/`score_confluence()` sekarang) — BUKAN gate AND baru. Faktor yg gak mendukung MENURUNKAN confidence, bukan MEMBUNUH sinyal total.
- **Sebelum nambah teori baru lagi ke skor, prioritaskan Part #2 (fitting logistic regression + regularization thd `trade_annotation` real)** — ini pengaman overfitting yg sesungguhnya: regularisasi (L1/L2) otomatis mengecilkan bobot faktor yg gak beneran nambah predictive value, gak perlu ditebak manual satu-satu.
- **Kriteria promosi walk-forward (bag. 7: PF net > 1.3 di ≥4/6 window, agreement > 60%)** adalah overfitting-check yg sesungguhnya (out-of-sample, multi-window) — prioritaskan bangun `trade_simulator.py`/`metrics.py` biar kriteria ini beneran bisa dijalankan, jangan cuma jadi target di atas kertas selagi teori terus numpuk.
- **Jalanin funnel-diagnostic** (hitung berapa % candidate/sentuhan yg survive tiap tahap: touch → structural gates → sinyal akhir) tiap kali ada faktor baru masuk ke `signal_runner.py` — kalau angka sinyal akhir collapse mendekati nol, itu tanda over-veto sblm sempat kena data production. Baseline saat ini (3 Juli 2026, sblm faktor baru manapun): 70 sentuhan → 3 sinyal (2 gate struktural doang, konfirmasi lolos di data real).

## 11. Kapabilitas #1 — Prediksi durasi (`duration_prediction.py`), DIIMPLEMENTASI 3 Juli 2026, mengikuti disiplin bag. 10

> **Verifikasi Claude Code**: skill baru terpisah (`skills/strategy/duration_prediction.py`), bukan bagian `fib_gann_timing.py`, sesuai kapabilitas #1 dari roadmap bag. 9 (dipilih founder sbg prioritas). **Dibangun dgn disiplin gate-vs-skor dari bag. 10 sejak awal**: `predict_duration()` MURNI informational, gak pernah nolak sinyal — mengembalikan estimasi (persentil jumlah bar + probabilitas outcome) yg bisa ditempel ke `Signal` sbg data tambahan, sama posisinya kayak `confidence` yg skor bukan filter.

**Dua bagian, pola deterministic-dulu-ML-belakangan (sama kayak `ConfluenceWeights`/`level_strength.py`)**:
- `build_duration_profile()`: kumpulin histori `fib_gann_timing.TripleBarrierLabel` (+ metadata arah & confidence tiap sinyal) jadi satu koleksi sampel — murni penyimpanan, gak ada perhitungan.
- `predict_duration()`: cari sampel historis yg cocok (arah + bucket confidence — LOW <0.5, MEDIUM 0.5-0.75, HIGH ≥0.75), lalu hitung persentil (p25/median/p75) jumlah bar sampai resolve DAN probabilitas empiris tiap outcome (TP/SL/TIMEOUT) dari hitungan sampel yg cocok — statistik deskriptif murni (`statistics.quantiles`), BUKAN model yg di-fit. Fallback eksplisit & terlihat (`matched_bucket` field): kalau bucket confidence spesifik kosong, turun ke seluruh sampel arah yg sama; kalau arah itu sendiri gak py histori sama sekali, balikin estimasi kosong (`sample_count=0`) — jujur "gak ada dasar historis", bukan ngarang angka. Sampel yg `censored` (kehabisan data sblm window resolusi, field yg sama dari `label_triple_barrier()`) dikecualikan dari statistik, sama alasan kayak `level_strength.py`.
- **Belum di-wire ke `signal_runner.generate_signals()`** — itu butuh dataset sinyal historis yg udah di-resolve (walk forward + label tiap sinyal masa lalu), yg itu tugasnya `trade_simulator.py` (masih belum dibangun, lihat bag. 6/gap). Round ini scope-nya cuma aggregator+predictor-nya doang, wiring ke live path round terpisah setelah pipeline itu ada.

**Verifikasi**: 10 test baru (`test_duration_prediction.py`, termasuk kasus bucket-matching, fallback direction-only, sampel tunggal gak crash, exclude censored, probabilitas jumlah = 1.0, isolasi LONG/SHORT gak ketuker) — 126 test total di `agent-orchestrator`, ruff clean.

**Verifikasi thd data (2 lapis, jujur soal batasannya)**:
- **Sintetis 400-candle** (`noisy_zigzag()`, dipakai jg di `test_signal_runner.py`) — 25 sinyal dihasilkan, dilabel via `label_triple_barrier()`. Hasil: SEMUA 25 sinyal resolve TIMEOUT (bukan TP/SL) — bukan bug, murni krn amplitudo osilasi seri sintetis ini (didesain buat nguji logic pivot/touch, bukan skala harga realistis) terlalu kecil relatif jarak TP1 hasil extension Fib (mis. entry 105.25, TP1 130.97 — butuh gerak +25.72, padahal seri ini reversal tiap 15 bar dgn increment cuma 0.5-2.0/bar). Yg tervalidasi dari run ini: pipeline nyambung end-to-end tanpa error, agregasi & bucketing & fallback (`direction_only` kepakai pas bucket "high" utk LONG kosong) semua bekerja bener di data yg beneran dihasilkan skill lain (bukan dikarang manual).
- **Cabang TP/SL campuran** (yg gak muncul di run sintetis di atas) dibuktikan lewat unit test eksak (`test_predict_duration_outcome_probabilities_sum_to_one`), bukan lewat data real/sintetis — jadi correctness matematikanya udah diverifikasi, cuma belum ada 1 dataset tunggal yg nunjukin ketiga outcome sekaligus dari data yg sama.
- **Real BTC/USDT 1h spot-check** (3 sinyal yg sama dipakai sepanjang sesi ini, dilabel `max_holding_bars=20`): idx=36 SHORT conf=0.782 → STOP_LOSS 7 bar; idx=56 SHORT conf=0.651 → TAKE_PROFIT 11 bar; idx=86 SHORT conf=0.594 → STOP_LOSS 7 bar. **n=3 — jelas TIDAK cukup buat persentil yg valid statistik**, tapi cukup buat spot-check "gak crash, hasilnya masuk akal" — dan kebetulan data real ini justru nunjukin campuran TP+SL asli (dua outcome beda), lebih representatif dari run sintetis di atas walau n-nya kecil banget.

**Kesimpulan**: fungsi aggregator/predictor-nya SUDAH BENAR (dibuktikan test eksak + smoke-test data nyata & sintetis), tapi **belum ada satupun distribusi yg cukup sampel utk dipakai produksi** — itu nunggu `trade_simulator.py` (generate dataset sinyal historis dlm jumlah besar) sblm `predict_duration()` beneran berguna dipakai. Konsisten sama prinsip bag. 10: ini estimator statistik deskriptif, bukan model yg di-fit, dan BELUM jadi gate apapun.

## 12. `trade_simulator.py` — DIIMPLEMENTASI 3 Juli 2026 (gap bag. 6, bukan gate apapun)

> **Verifikasi Claude Code**: `validation/fib_gann_backtest/trade_simulator.py` — bungkus `fib_gann_timing.label_triple_barrier()` (labeling TP/SL/timeout yg udah ada) + deduksi biaya funding, sesuai spek "Metrics — funding-aware (WAJIB, bukan opsional)" (bag. sblmnya di dok ini). **Murni layer labeling/pengukuran — gak nambah gate apapun**, konsisten sama prinsip bag. 10: gak ada sinyal yg ditolak di modul ini, cuma diukur hasilnya.

**Desain**:
- `FundingEvent(ts, rate)` — satu snapshot funding (bukan estimasi prorata kontinu, sesuai brief "funding accumulation snapshot-based").
- `simulate_trade(signal, granular_candles, funding_events, max_holding_bars)`: label via `label_triple_barrier()`, lalu jumlahkan `FundingEvent` yg `ts`-nya jatuh di dalam window holding `[signal.ts, label.exit_ts]` (inklusif kedua ujung — simplifikasi eksplisit utk kasus langka sinyal masuk/keluar pas di timestamp funding). **Penyesuaian arah**: `funding_rate` positif = long bayar short (konvensi universal perp) → LONG akumulasi `+rate` (biaya), SHORT akumulasi `-rate` (biaya negatif = untung). `net_return_pct = label.return_pct - funding_cost_pct`.
- `simulate_trades(signals, candles, funding_events, max_holding_bars)`: versi batch, skip sinyal yg gak py candle lanjutan sama sekali (sinyal di bar terakhir seri).
- 9 test baru (`test_trade_simulator.py`) — LONG kena biaya nurunin net return, SHORT untung (funding jadi net benefit, `net_return_pct > gross_return_pct`), event di luar window dikecualikan, event PERSIS di boundary window (masuk & keluar) tetap dihitung, penjumlahan multi-event, flag `censored` dari label tetap kepreserve, batch skip sinyal tanpa candle lanjutan. 135 test total di `agent-orchestrator`, ruff clean.

**Verifikasi thd data real (2 percobaan, keduanya nemuin gap data nyata — bukan bug kode)**:
- **Cek langsung ke tabel `funding_rate` production** (via Neon HTTP-SQL endpoint, `SELECT ... GROUP BY venue, symbol`): cuma **1 baris** utk BTC/USDT (`2026-07-01 20:46:41`, sedikit di LUAR window 100-candle BTC/USDT 1h yg dipakai sepanjang sesi ini) dan 1 baris utk ETH. Konfirmasi konkret bhw `ingest.py` (standalone script, belum di-wire ke scheduler/Inngest — dicatat dari round ingestion sebelumnya) memang belum pernah dijalankan dgn volume berarti utk funding_rate — bukan masalah kode `trade_simulator.py`, tapi gap data upstream yg baru kekonfirmasi eksplisit di sini.
- **Run thd 3 sinyal real BTC/USDT 1h + funding harian CoinGlass** (probe yg sama dari bag. 9, konvensi unit persen-vs-fraksi belum dikonfirmasi, dipakai apa adanya cuma utk ilustrasi): SEMUA 3 sinyal dapet `funding_events_count=0` — bukan bug, murni krn snapshot harian CoinGlass berjarak 24 jam (persis tengah malam UTC), sementara window holding ketiga sinyal itu cuma 7-11 jam, jadi gak pernah ada satupun timestamp harian yg jatuh di dalam window sesempit itu. **Temuan nyata**: data funding granularity HARIAN gak akan pernah bisa exercise mekanisme funding-cost ini utk trade berdurasi pendek (<24 jam, yg justru umum di setup 1h founder) — funding_rate table native (interval 8 jam per `funding_interval_hours` di skema DB) WAJIB diisi beneran dulu sblm fitur funding-aware ini pernah keliatan efeknya nyata di data.

**Kesimpulan**: mekanisme deduksi funding-nya SUDAH BENAR secara matematika (dibuktikan test eksak: LONG rugi, SHORT untung, boundary inklusif, exclude-di-luar-window, sum multi-event) — tapi **belum ada satu kalipun kesempatan mengujinya thd funding_rate historis nyata**, krn datanya sendiri belum ada dlm volume yg cukup. Ini gap data (ingestion belum dijalankan berkelanjutan), bukan gap logic `trade_simulator.py`.
