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

## 13. Leverage/liquidation-aware simulation — DIIMPLEMENTASI 3 Juli 2026 (`docs/shadow-simulator-brief.md` bag. 1-2)

> **Verifikasi Claude Code**: founder minta trade_simulator bisa membedakan paper vs uang beneran — spesifiknya, dampak initial margin/leverage/cross-isolated margin. Sebelum ini dibangun, pengecekan lapangan nemuin 2 fakta penting: (1) `apps/products/trading/execution/` (risk_gate.py, custody/) **masih kosong total**, cuma README + `.gitkeep` — belum ada kode eksekusi order beneran sama sekali; (2) `trade_simulator.py` yg ada (bag. 12) **sama sekali gak punya konsep leverage/liquidation** — dia asumsikan posisi selalu bertahan sampai SL struktural. Founder lalu kasih `docs/shadow-simulator-brief.md` (disimpan penuh di repo, companion dokumen ini) yg secara eksplisit mengurutkan: bangun leverage/liquidation-aware simulator DULU (buildable tanpa data trade real), perluasan `trade_annotation` + shadow-pairing + ML SETELAHNYA. Round ini scope-nya CUMA poin 1-2 brief itu.

**Desain** (`validation/fib_gann_backtest/trade_simulator.py`, ADITIF — `SimulatedTrade`/`simulate_trade`/`simulate_trades` yg lama gak diubah sama sekali):
- **Penyimpangan dari spek brief, didokumentasikan eksplisit**: brief nulis `initial_margin: float # notional / leverage` (tersirat dolar). Modul ini gak pernah nge-track notional/qty/equity dolar di manapun (`return_pct`-based sepenuhnya, konsisten sama `SimulatedTrade`) — jadi `initial_margin_fraction = 1/leverage` diimplementasi sbg FRAKSI notional, bukan dolar. Ini bikin semua formula position-size-agnostic otomatis (berlaku utk ukuran posisi berapapun), bukan sekadar jalan pintas.
- `MarginContext(leverage, margin_mode, initial_margin_fraction, maintenance_margin_rate, cross_buffer_pct, liquidation_price)` — `liquidation_price` DIHITUNG (`build_margin_context()`), gak pernah diinput langsung, persis sesuai brief.
- **Liquidation price** (simplifikasi MVP, flat `maintenance_margin_rate` per brief, bukan tier real Binance by-notional): `cushion = initial_margin_fraction + cross_buffer_pct - maintenance_margin_rate`; LONG liquidasi di `entry*(1-cushion)`, SHORT di `entry*(1+cushion)`. **CROSS margin mode**: `cross_buffer_pct` (default 0.0) merepresentasikan equity tambahan dari akun yg nge-backstop posisi ini di luar margin isolated-nya sendiri — simplifikasi jujur, krn simulator per-sinyal ini gak py state portfolio-wide buat nurunin angka itu otomatis, caller yg nyuplai.
- **Liquidation check SEBELUM SL check, tiap bar** (`simulate_leveraged_trade()`) — walk forward SENDIRI (bukan reuse `label_triple_barrier()`), krn butuh cek tambahan yg gak ada hook-nya di fungsi lama itu, DAN threshold liquidation-nya sendiri bergeser tiap bar krn funding erosion (di bawah).
- **Funding erosion**: `cumulative_funding_fraction` (sign sama kayak `simulate_trade`'s `_funding_cost_pct`) dikurangkan dari cushion tiap bar SEBELUM cek price barrier — posisi bisa ke-liquidasi murni dari erosi funding tanpa harga bergerak lawan sama sekali (dibuktikan test: harga FLAT 5 bar, funding cost kumulatif ngelewatin cushion, tetep LIQUIDATED).
- `max_safe_leverage(entry, sl, atr, mmr, buffer_k)` + `assert_liquidation_safe(...)` (raise `UnsafeLeverageError`, fail-fast bukan warning) — **eksak secara aljabar, bukan aproksimasi**: `max_safe_leverage()` mengembalikan PERSIS leverage di mana liquidation distance = required buffer (dibuktikan test `test_max_safe_leverage_is_exactly_the_assert_boundary` — leverage itu sendiri lolos assert, 1% di atasnya gagal).
- 22 test baru (`test_trade_simulator_leverage.py`), 157 test total di `agent-orchestrator`, ruff clean.

**Verifikasi thd 3 sinyal real BTC/USDT 1h** (pivot & exit plan yg sama dipakai sepanjang sesi ini): dihitung `max_safe_leverage` per sinyal dari SL & ATR real-nya, lalu simulasi di 5x/10x/~90%-dari-max-safe:

| sinyal | SL distance | ATR | max_safe_leverage | outcome (semua leverage, gak ada yg liquidated) |
|---|---|---|---|---|
| idx=36 SHORT | 0.52% | 474.56 | 58.36x | STOP_LOSS, margin_return 5x=-2.62% → 45x=-23.57% |
| idx=56 SHORT | 1.53% | 458.71 | 37.05x | TAKE_PROFIT, margin_return 5x=+11.58% → 33.34x=+77.24% |
| idx=86 SHORT | 1.47% | 428.23 | 38.55x | STOP_LOSS, margin_return 5x=-7.33% → 34.69x=-50.83% |

**Konfirmasi konkret leverage MENGAMPLIFIKASI return notional yg SAMA jadi hasil margin yg jauh berbeda** — exit_reason (STOP_LOSS/TAKE_PROFIT) SAMA persis di semua level leverage yg dites (krn semuanya di bawah batas aman per sinyal), tapi margin_return_pct-nya membentang dari puluhan persen sampai lebih dari 50-77% cuma dari leverage yg beda, dari SATU harga exit yg sama. Ini persis "eksposur uang beneran sangat berbeda" yg dimaksud founder.

**Temuan penting yg HARUS dicatat, bukan dianggap "aman" begitu saja**: `max_safe_leverage` di ketiga sinyal ini jatuh di range 37-58x — angka yg secara matematis valid (lolos invariant liquidation-vs-SL) tapi **jauh di atas leverage yg wajar dipakai beneran** (RiskMandate schema `max_leverage` default cuma 3x). Ini KENAPA brief eksplisit taruh "Absolute max leverage cap per simbol (set manual, mis. 10-20x majors)" di daftar **"TIDAK BOLEH dipelajari ML / hard-coded rule"** (bag. 5) — formula `max_safe_leverage()` cuma menjamin "liquidation gak kejadian sebelum SL", BUKAN "leverage ini aman scr keseluruhan" (belum masuk slippage eksekusi, gap harga, risk exchange-specific, dst). **Belum diimplementasi round ini**: hard cap absolut itu sendiri — round ini cuma formula liquidation-vs-SL-nya, bukan lapisan safety di atasnya.

**Belum dikerjakan (brief bag. 7, poin 3-6)**: perluasan skema `trade_annotation` (kolom eksekusi real), `shadow_pair` pairing + divergence attribution (7 komponen: entry_slippage/exit_slippage/timing_deviation/size_leverage_effect/fees_funding_delta/manual_override/residual), fidelity score, ML risk envelope. Semua itu butuh founder mulai mencatat trade real (poin 3), belum bisa dimulai round ini.

## 14. Perluasan skema `trade_annotation` — DIIMPLEMENTASI 3 Juli 2026 (brief bag. 7 poin 3)

> **Verifikasi Claude Code**: migration `0005_trade_annotation_execution_columns.py` — 7 kolom baru ke `trade_annotation` (`packages/db/src/kinetiq_db/models.py` + migration, `packages/db/migrations/` adalah path CODEOWNERS-protected, **wajib manual review founder sebelum merge**, gak di-auto-merge sesi ini walau CI hijau). Ini "sisi real" dari `shadow_pair` yang bakal dibangun poin 4 nanti — belum ada pairing/kolom `signal_id` apapun round ini, sengaja, sesuai scope brief poin 3 doang.

**Kolom baru** (semua nullable — brief eksplisit: "Sinyal tanpa trade real tetap disimulasikan dan dicatat (sisi real kosong)"):
- `leverage` (`Numeric(6,3)`, sama tipe kayak `Position.leverage`/`RiskMandate.max_leverage`)
- `margin_mode` (`Text`, CHECK `in ('cross','isolated')`)
- `entry_fill_price`, `exit_fill_price` (`Numeric(24,10)`, sama tipe kayak `Position.entry_price`)
- `fees_paid_usd`, `funding_paid_usd` (`Numeric(24,4)`)
- `exit_reason_real` (`Text`, CHECK `in ('stop_loss','take_profit','liquidated','timeout','manual_override')` — 5 nilai, termasuk `manual_override` yg brief bag. 3 sebut eksplisit sbg kategori exit real yg beda dari TP/SL/timeout/liquidated sistem)

**Penyimpangan dari nama literal brief, didokumentasikan eksplisit**: brief nulis `fees_paid`/`funding_paid`, di sini jadi `fees_paid_usd`/`funding_paid_usd` — biar konsisten sama konvensi penamaan dolar yg udah ada di skema ini (`RiskMandate.max_position_notional_usd`, `max_daily_loss_usd`), dan biar gak ambigu sama `trade_simulator.py`'s fraksi persen-dari-notional (`funding_cost_pct` dst.) — tabel ini diisi manual sama manusia langsung dari histori trade exchange-nya (dalam dolar), bukan hasil hitungan fraksi.

**Diverifikasi penuh upgrade→downgrade→upgrade thd Postgres 16 lokal beneran** (bukan cuma baca kode, sesuai disiplin migration sblmnya): fresh database, `alembic upgrade head` (0001→0005) sukses, `\d trade_annotation` konfirmasi tipe kolom + 2 CHECK constraint persis sesuai desain, insert row dgn sisi real KOSONG SEMUA sukses, insert row dgn sisi real TERISI PENUH sukses, insert dgn `margin_mode`/`exit_reason_real` invalid keduanya DITOLAK CHECK constraint (dibuktikan langsung, bukan diasumsikan), `alembic downgrade -1` sukses balikin skema persis ke bentuk semula (7 kolom + 2 constraint hilang, baris lama tetap ada), `alembic upgrade head` lagi sukses replay bersih.

**Belum dikerjakan (brief bag. 7, poin 4-6)**: `shadow_pair` pairing (butuh `signal_id` linkage yg belum ada di round ini) + divergence attribution, fidelity score, ML risk envelope. Semua itu masih butuh founder ACTUALLY mulai isi kolom baru ini dari trade real-nya dulu — skema udah siap dipakai, belum ada barisnya.

## 15. Kapabilitas #2 — Reversal vs continuation setelah SL (`post_stop_behavior.py`), DIIMPLEMENTASI 3 Juli 2026

> **Verifikasi Claude Code**: skill baru terpisah (`skills/strategy/post_stop_behavior.py`), kapabilitas #2 dari roadmap bag. 9. Klaim founder: begitu SL kena, harga akan "pulang ke rumah" (RETRACE_TO_ENTRY — thesis arah bener, cuma ke-stop prematur) atau bikin "tujuan baru arah berlawanan" (REVERSAL_CONTINUATION — reversal beneran). **Manfaatin CHoCH/BOS detector yg udah ada** (`market_structure.py`) persis sesuai saran founder sebelumnya, sbg bukti pendukung (bukan gate kedua) buat REVERSAL_CONTINUATION.

**Desain, disiplin gate-vs-skor (bag. 10) sejak awal — murni informational**:
- `classify_post_stop_behavior()`: jalan maju dari bar SL kena, cari mana yg kejadian LEBIH DULU — close balik ≥/≤ `entry_price` (RETRACE_TO_ENTRY) atau close ngelewatin `stop_loss ± continuation_atr_multiplier*ATR` di arah yg sama kayak break SL (REVERSAL_CONTINUATION). Dua threshold ini SELALU di sisi berlawanan dari `stop_loss` relatif `entry_price` — jadi gak ada kasus 1 candle nyentuh keduanya sekaligus (beda dari TP/SL di `label_triple_barrier()` yg butuh aturan same-candle-tie-break eksplisit, di sini gak perlu). Kalau REVERSAL_CONTINUATION kejadian, dicek juga apakah `market_structure.detect_structure_event()` di bar yg sama nunjukin CHoCH/BOS di arah kontinuasi yg sama — hasilnya disimpan di `structure_confirmed` sbg bukti tambahan, BUKAN gate kedua (reversal tanpa konfirmasi struktur tetap diklasifikasi REVERSAL_CONTINUATION, cuma dicatat lebih lemah).
- Kalau gak ada satupun kejadian dlm window (`max_lookforward_bars`, default 10): CHOP (genuinely inconclusive) atau CHOP+`censored=True` kalau kehabisan data historis sblm window selesai — disiplin right-censoring yg sama persis kayak `label_triple_barrier()`/`level_strength.py`.
- `build_post_stop_profile()`/`predict_post_stop_outcome()`: agregator probabilitas empiris P(outcome) per arah trade — **sengaja cuma di-bucket per arah doang** (gak per-confidence spt `duration_prediction.py`), krn belum ada cukup sampel real buat justify pembagian lebih halus — bisa ditambah nanti kalau volume `trade_annotation` udah ada.
- 15 test baru (172 total di `agent-orchestrator`), ruff clean.

**Diverifikasi thd 2 sinyal real BTC/USDT 1h yg kena SL** (dari 3 sinyal yg sama dipakai sepanjang sesi ini):
- **idx=36** (SHORT, SL kena di bar 43): klasifikasi **RETRACE_TO_ENTRY**, resolve 1 bar setelah SL (bar 44) — harga bener2 balik ke area entry cepet, konsisten sama "thesis arah bener, cuma ke-stop prematur".
- **idx=86** (SHORT, SL kena di bar 93): klasifikasi **REVERSAL_CONTINUATION**, resolve 1 bar setelah SL (bar 94), **DAN `structure_confirmed=True`** — CHoCH/BOS bullish beneran kedeteksi di bar yg sama. **Ini nyambung LANGSUNG ke temuan round market_structure sebelumnya** (`docs/prd.md` status B.6): CHoCH bullish yg udah ketemu persis di pivot LOW idx=91, diikuti 7 BOS bullish berturut-turut ("harga rally cepat abis pivot") — bar 94 pas ada di tengah rally itu. Dua modul yg dibangun beda round, dari data yg sama, saling mengonfirmasi temuan yg sama persis — bukan kebetulan, bukti detektornya konsisten.
- **2 dari 2 sampel real yg kena SL menghasilkan KEDUA outcome yg berbeda** (bukan cuma 1 jenis doang spt yg kejadian di verifikasi sintetis `duration_prediction.py` sebelumnya yg semua TIMEOUT) — sampel kecil (n=2) jelas belum cukup buat `predict_post_stop_outcome()` beneran dipakai produksi, tapi cukup buat bukti korektnes kode di kedua cabang outcome DAN cabang `structure_confirmed`, dari data real bukan dikarang.

**Belum dikerjakan**: fitting `predict_post_stop_outcome()` ke bobot confidence scoring (Part #2, sama pola semua skill lain sesi ini — nunggu volume `trade_annotation` yg cukup), bucket per-confidence, dan wiring ke `signal_runner.py`/`score_confluence()` (belum ada keputusan desain gimana faktor ini masuk formula, sama kayak `level_strength.py`).

## 16. `metrics.py` — DIIMPLEMENTASI 3 Juli 2026 (gap bag. 6, "Metrics — funding-aware")

> **Verifikasi Claude Code**: `validation/fib_gann_backtest/metrics.py`. Mengisi gap terakhir yg tersisa dari bag. 6 (validation harness): PF/Sharpe/max-drawdown dari `SimulatedTrade`, sesuai spek "Metrics — funding-aware (WAJIB, bukan opsional)" yg udah dicatat sblm ini di dokumen ini.

**Desain**:
- Setiap metrik dihitung DUA KALI — gross (`label.return_pct`, raw price PnL) dan net (`net_return_pct`, stlh funding) — dilaporkan berdampingan, sesuai brief eksplisit ("gap besar = strategi terlalu bergantung raw momentum yg dimakan biaya holding").
- **Sharpe di-annualize dari durasi holding AKTUAL** (`label.exit_ts - signal_ts`, waktu kalender real per trade) — BUKAN asumsi 252 trading days, sesuai spek brief persis ("crypto perp 24/7 dgn holding period tidak seragam"). `trades_per_year = 365.25 hari / rata² durasi holding`.
- `_profit_factor()`: `None` (bukan infinity) kalau gak ada losing trade sama sekali — undefined, bukan angka besar yg bisa disalahartikan.
- `_max_drawdown_pct()`: equity curve compounding (`equity *= 1+return`), butuh urutan KRONOLOGIS — `compute_metrics()` nge-sort by `signal_ts` internal, gak bergantung urutan input caller.
- **Trade `censored` DIKECUALIKAN dari semua perhitungan** (disiplin right-censoring yg sama persis kayak seluruh modul lain sesi ini) — `censored_count` dilaporkan terpisah biar transparan, bukan hilang diam-diam.
- `compute_metrics_by_regime(trades, regime_of)`: breakdown per regime (RISK_ON/OFF/NEUTRAL/FREEZE) yg diminta brief — **arsitekturnya udah ada via callable `regime_of` yg pluggable, TAPI belum pernah diverifikasi thd regime data real**, krn `market_regime.py` (PRD B.6) belum dibangun sama sekali — gak ada label regime asli buat di-group. Sama persis caveat "mekanisme udah ada, belum divalidasi thd hal yg dimaksud" kayak Gann-angle touch-tracking di `level_strength.py`.
- 13 test baru (185 total di `agent-orchestrator`), ruff clean.

**Diverifikasi thd 3 sinyal real BTC/USDT 1h yg sama dipakai sepanjang sesi ini**:
```
trade_count=3  censored_count=0
win_count=1  loss_count=2
profit_factor_gross=1.165  profit_factor_net=1.165  (sama krn funding_events=[] — konsisten sama gap data funding_rate bag. 12)
sharpe_gross=1.801  sharpe_net=1.801
max_drawdown_pct=0.0147  (1.47%)
avg_holding_duration_hours=8.33  trades_per_year=1051.9
```
**Kesimpulan jujur**: arithmetic-nya BENAR di data real (gross=net krn belum ada funding event yg exercise, konsisten sama temuan bag. 12), tapi **n=3 jauh dari cukup buat angka PF/Sharpe/drawdown ini beneran dianggap valid statistik** — ini cuma bukti korektnes kode ujung-ke-ujung dari data real, bukan validasi performa strategi. Kriteria promosi bag. 7 (PF net > 1.3 di ≥4/6 window walk-forward) butuh jauh lebih banyak sinyal + window walk-forward asli (`run_validation.py`, masih belum dibangun) sblm bisa dijalankan beneran.

**Belum dikerjakan (sisa dari bag. 6)**: `report.py` (dump hasil ke `docs/validation-results/`), `configs/walk_forward_windows.yaml` + `run_validation.py` (CLI yg nge-wire `data_loader → signal_runner → trade_simulator → metrics` across window walk-forward `packages/backtest-core`) — ini yg dibutuhkan sblm kriteria promosi bag. 7 beneran bisa dites.

## 17. `report.py` + `run_validation.py` + `configs/walk_forward_windows.yaml` — DIIMPLEMENTASI 3 Juli 2026 (gap terakhir bag. 6)

> **Verifikasi Claude Code**: gap terakhir bag. 6 kelar — `validation/configs/walk_forward_windows.yaml` (1 file YAML dipakai bareng, sesuai spek "train_months, test_months, embargo_days, mode di satu file YAML"), `validation/fib_gann_backtest/run_validation.py` (CLI, support `--dry-run`), `validation/fib_gann_backtest/report.py` (dump JSON+Markdown ke `docs/validation-results/`, BUKAN tabel DB baru, sesuai spek).

**Desain `run_validation.py`**:
- Nge-wire `data_loader.load_candles()` → `generate_windows_by_calendar()` (`packages/backtest-core`, skema kalender yg emang dipakai `fib_gann_backtest` per docstring package itu sendiri, bukan skema candle-count MARKOVIZ) → per window: `signal_runner.generate_signals()` → `trade_simulator.simulate_trades()` → `metrics.compute_metrics()`.
- **Gak ada gimmick warmup-window terpisah**: tiap window, SEMUA candle sampai `test_end` di-feed ke `generate_signals()` (yg emang udah causal via `as_of` walk-nya sendiri), lalu cuma sinyal yg `ts`-nya jatuh di `[test_start, test_end)` yg dihitung — manfaatin disiplin no-lookahead yg udah ada, gak perlu nebak-nebak panjang buffer warmup terpisah.
- Window yg gak py trade non-censored sama sekali → `metrics=None` (bukan crash, bukan angka 0 palsu) — DAN tetap dihitung GAGAL di kriteria promosi (window yg gak pernah trading gak membuktikan apa-apa, bukan dikecualikan dari penyebut).
- **Cuma kriteria promosi PF yg dicek** (`PF net > threshold di ≥ pf_pass_fraction dari window`) — kriteria KEDUA brief ("Agreement rate > 60% terhadap `trade_annotation`") **secara eksplisit dilaporkan "belum bisa dihitung"**, BUKAN diam-diam di-skip — `trade_annotation` belum py kolom `signal_id` (migration 0005), jadi gak ada dasar buat cocokin ke sinyal spesifik mana pun.
- `--dry-run`: load candle + generate window set + print preview, TANPA jalanin backtest apapun & TANPA nulis report — cara aman ngecek config/cakupan tanggal sblm commit ke run penuh.

**Bug nyata ketemu & di-fix pas nulis test (bukan pas run production)**: `pf_pass_fraction: 0.6667` di config awal (representasi desimal dari "4 dari 6" yg DIBULATKAN KE ATAS) ternyata bikin kasus "PERSIS 4 dari 6 window lolos" GAGAL kriteria promosinya sendiri — `4/6 = 0.66666...`, yg secara matematis LEBIH KECIL dari `0.6667`. Ini kontradiksi langsung sama kata-kata brief ("minimal 4 dari 6"). **Fix**: dibulatkan ke BAWAH jadi `0.6666`, dikunci via test (`test_promotion_pf_stats_counts_windows_strictly_above_threshold`). Contoh konkret kenapa harus selalu nulis test dgn angka pasti, bukan cuma percaya logic-nya "keliatan benar".

**18 test baru** (`test_run_validation.py` 11, `test_report.py` 7), 203 test total di `agent-orchestrator`, ruff clean.

**Verifikasi thd data real, 2 lapis**:
- **`data_loader.load_candles()` sendiri TETAP TIDAK BISA dijalankan langsung dari sandbox sesi ini** — persis batasan yg udah dicatat sblm ini di sesi ini: raw koneksi psycopg/port Postgres (yg dipakai `SQLAlchemy create_engine()`) hang total di sandbox ini, cuma endpoint HTTP-SQL Neon (`curl POST .../sql`) yg reachable. Dicoba langsung (`python3 run_validation.py --dry-run`), beneran hang, di-`TaskStop` manual — BUKAN bug kode, GitHub Actions runner (atau founder langsung) yg jadi integration test asli utk bagian ini, sama persis kayak `data_loader.py`/`ingest.py` sblmnya.
- **Sisa pipeline (`run_window`/`run_validation`/`report.write_report`) diverifikasi PENUH thd 100 candle BTC/USDT 1h real** (dimuat langsung dari cache HTTP-SQL, bypass `data_loader.py`, pola yg sama dipakai di semua verifikasi round ini): (1) config walk-forward asli (1 bulan train + 1 bulan test) thd 100 candle 1h yg cuma mencakup ~4 hari — **BENERAN ngasih 0 window**, dikonfirmasi eksplisit bhw ini krn data production emang belum cukup panjang (bukan bug) — temuan penting: **kriteria promosi bag. 7 secara harfiah TIDAK BISA dites thd data production SEKARANG**, ingestion candle historis dlm jumlah besar (bukan cuma ~100 candle) WAJIB ada dulu; (2) window custom yg disesuaikan ukurannya (25 jam per window, bukan sebulan) dites end-to-end thd 100 candle real yg sama — 2 window, masing² 1 sinyal, metrics dihitung bener (termasuk kasus `PF=None` pas gak ada losing trade & `PF=0.0` pas cuma ada losing trade), report JSON+Markdown ke-generate bener & ke-baca ulang bener.

**Kesimpulan**: seluruh mekanisme (window generation → signal filtering per window → simulasi → metrics → report) SUDAH BENAR dan diverifikasi ujung-ke-ujung thd data real. **Yang masih blm bisa dilakukan**: kriteria promosi bag. 7 beneran dites thd walk-forward calendar-scale (butuh data historis jauh lebih panjang dari yg ada di production sekarang) dan kriteria agreement-rate (butuh `signal_id` linkage ke `trade_annotation`, scope round terpisah). Dengan ini, **SEMUA komponen validation harness bag. 6 SUDAH DIBANGUN** — `data_loader.py`, `signal_runner.py`, `trade_simulator.py` (funding + leverage aware), `metrics.py`, `report.py`, `run_validation.py`, `configs/walk_forward_windows.yaml` — yg tersisa cuma soal VOLUME DATA, bukan lagi soal kode yg belum ditulis.

## 18. Kapabilitas #3 — Bias sesi jam (`session_bias.py`), DIIMPLEMENTASI 3 Juli 2026, DENGAN KOREKSI status "blocked"

> **Koreksi eksplisit thd dokumentasi bag. 9 sblmnya**: waktu itu ditulis kapabilitas #3 "terblokir data" krn CoinGlass Hobbyist cuma kasih data harian utk funding/OI/liquidation. Itu BENAR utk 3 jenis data itu, tapi **gak relevan buat kapabilitas ini** — tagging sesi cuma butuh timestamp candle-nya sendiri (jam berapa dlm UTC), dan `apps/products/trading/ingestion/` udah narik candle **hourly** langsung dari Binance/Bybit/Hyperliquid sejak awal sesi ini, SAMA SEKALI gak lewat CoinGlass. Kesimpulan yg bener: kendala aslinya adalah **VOLUME data** (production cuma ~4 hari candle history, persis kendala yg bikin `run_validation.py` ngasih 0 window walk-forward di bag. 17), BUKAN granularity. Mekanismenya sendiri SEPENUHNYA bisa dibangun & dites sekarang.

**Desain** (`skills/strategy/session_bias.py`, skill baru terpisah):
- `session_of(ts, boundaries=DEFAULT_SESSION_BOUNDARIES_UTC)`: klasifikasi jam UTC ke ASIA (00-08)/LONDON (08-16)/NEW_YORK (13-21)/LONDON_NY_OVERLAP (13-16, window liquidity tertinggi, sengaja dipisah bukan ditimpa ke salah satu)/OFF_HOURS. **Batas jam ini konvensi awal yg bisa diubah, BUKAN definisi founder yg udah dikonfirmasi** — sama persis caveat "starting point, bukan hasil kalibrasi" yg dipakai semua `DEFAULT_*` lain di codebase ini (mis. `fib_gann_timing.DEFAULT_ZIGZAG_ATR_MULTIPLIER`).
- `group_into_session_blocks()`: sesi itu PERIODE kontinu, bukan candle independen — candle berturutan yg sesi+tanggal-nya sama digabung jadi 1 block sblm dihitung return-nya (biar sesi Asia yg py 8 candle gak "berbobot lebih" drpd overlap yg cuma py 3 candle kalau di-treat per-candle).
- `compute_session_bias()`: agregat deskriptif per sesi (mean/median return, fraksi block yg closing positif) — **murni statistik pasar mentah, gak nyentuh sinyal/gate apapun**, sesuai prinsip gate-vs-skor bag. 10 by construction (gak ada yg ditolak di modul ini sama sekali).
- 16 test baru (219 test total di `agent-orchestrator`), ruff clean.

**Diverifikasi thd 100 candle BTC/USDT 1h real yg sama dipakai sepanjang sesi ini** (4 hari 3 jam, 27 Jun–1 Jul 2026): 21 session block ke-generate bener (grouping per tanggal+sesi kerja persis sesuai desain — verifikasi manual tabel penuh cocok sama ekspektasi). Agregat per sesi (n=4-5 tiap sesi, **jelas jauh dari cukup buat klaim statistik**, cuma bukti korektnes kode):
```
asia                 n=4  mean=+0.03%  median=+0.28%  positive_fraction=0.75
london               n=4  mean=-0.58%  median=-0.27%  positive_fraction=0.25
london_ny_overlap    n=4  mean=+0.46%  median=-0.12%  positive_fraction=0.25
new_york              n=5  mean=+0.00%  median=-0.17%  positive_fraction=0.40
off_hours            n=4  mean=-0.21%  median=-0.16%  positive_fraction=0.00
```
**Catatan menarik (bukan kesimpulan)**: `positive_fraction` Asia = 0.75 (3 dari 4 hari closing lebih tinggi) — arahnya KONSISTEN sama klaim founder ("jam Asia sering long/naik"), tapi n=4 per sesi itu sepele secara statistik (bandingkan: bahkan koin fair 50/50 py peluang lumayan besar dpt 3/4 di sampel sekecil ini). **Ini sama sekali BUKAN validasi klaim founder** — cuma bukti mekanismenya jalan bener di data real. Klaim itu baru bisa beneran diuji begitu ada puluhan/ratusan hari data historis, bukan 4.

**Belum dikerjakan**: wiring `session_of()`/`compute_session_bias()` ke `signal_runner.py`/`score_confluence()` sbg faktor tambahan (keputusan desain terpisah, sama kayak `level_strength.py`), dan skala data historis yg jauh lebih besar sblm klaim founder beneran bisa dikonfirmasi/ditolak.

## 19. `log_trade_annotation.py` — DIIMPLEMENTASI 3 Juli 2026 (brief bag. 7 poin 3, langkah founder mulai catat trade real)

> **Verifikasi Claude Code**: founder minta lanjut ke "mulai isi `trade_annotation` real" (poin 3 brief bag. 7, yg buka jalan ke `shadow_pair`/fidelity/ML — bag. 5's cold start eksplisit: "sebelum ada ≥ ~50 pasangan shadow, SEMUA parameter pakai default rule-based"). Skema tabelnya udah ada (migration 0005), tapi INSERT manual lewat raw SQL itu error-prone (UUID tenant_id, FK instrument_id, dan yg PALING gampang kelewat: RLS). Dibangun CLI (`skills/strategy/scripts/log_trade_annotation.py`) biar founder gak perlu nulis SQL sendiri.

**Desain**:
- Semua kolom OPSIONAL kecuali `tenant`/`instrument`/`ts`/`action` (kolom NOT NULL asli tabel) — trade real yg dicatat sblm analisis fib/gann-nya lengkap tetep data valid, simetris sama poin brief "sinyal tanpa trade real tetap valid".
- Resolve `--venue`+`--symbol` → `instrument_id` dan `--tenant-id` ATAU `--tenant-email` (mutually exclusive, `--tenant-email` lebih gampang diinget drpd UUID) → `tenant_id`, lewat lookup DB, bukan ditebak.
- Validasi client-side via `argparse choices=` pas persis sama 2 CHECK constraint migration 0005 (`margin_mode`, `exit_reason_real`) — pesan error jelas SEBELUM nyoba connect DB, bukan nunggu Postgres nolak.
- `--dry-run` (pola yg sama dipakai di semua tool CLI sesi ini): preview JSON persis apa yg BAKAL di-insert, gak nyentuh DB sama sekali.
- **Gotcha RLS yg WAJIB ditangani, bukan opsional**: `trade_annotation` py `FORCE ROW LEVEL SECURITY` (`docs/prd.md` bag. B.4) — INSERT ditolak WITH CHECK clause kalau `app.tenant_id` gak di-set PERSIS sama tenant_id baris yg diinsert, di sesi yg sama. Tool ini set itu via `SELECT set_config('app.tenant_id', ..., false)` (bukan bare `SET` — itu syntax error sesuai gotcha `docs/deployment-runbook.md`) SEBELUM insert. Raw `psql INSERT` manual (skenario yg coba dihindari tool ini) bakal ketolak diam² kalau lupa langkah ini.

**Bug nyata ketemu pas simulasi CI (2 KALI, pola yg sama persis)**: modul ini awalnya import `kinetiq_db`/`sqlalchemy` di level module — persis bug yg ketemu di PR `run_validation.py` sebelumnya (bag. 17): job `test` CI gak install `packages/db`, jadi collection test PYTEST-nya sendiri gagal walau test-nya gak pernah manggil DB sama sekali. **Ketangkep SENDIRI kali ini sblm push** (bukan nunggu CI merah dulu) krn udah belajar dari bug sebelumnya — jalanin simulasi venv fresh + install persis command CI SEBELUM push jadi kebiasaan tetap mulai round ini. Fix: import `kinetiq_db`/`sqlalchemy` dipindah jadi lazy (di dalam fungsi yg beneran butuh, bukan level module).

**10 test baru** (`test_log_trade_annotation.py`, fungsi murni: `parse_ts`, `build_row`, `build_parser`, dry-run `main()`), 229 test total di `agent-orchestrator`. Simulasi CI persis (fresh venv, `pip install -e "packages/backtest-core[dev]" pytest pyyaml`, `pytest packages/backtest-core/tests agent-orchestrator/tests`) → **250 test lulus** (229 + 21 `backtest-core`).

**Diverifikasi END-TO-END thd Postgres 16 lokal beneran** (fresh DB, migration 0001-0005 penuh, role non-superuser sbg owner tabel — bukan `postgres` role, krn superuser selalu bypass RLS, gak valid dites pakai itu, disiplin yg sama dipakai semua verifikasi RLS sesi ini): (1) insert REAL via role non-superuser via tool ini — SUKSES, semua field (8 kolom lama + 7 kolom eksekusi baru migration 0005) ke-persist bener termasuk `swing_ref` JSONB nested; (2) insert TANPA `set_config` sama sekali (simulasi "lupa" langkah RLS) — **DITOLAK** `psycopg.errors.InsufficientPrivilege`, dibuktikan langsung bukan diasumsikan; (3) insert DENGAN `app.tenant_id` di-set ke tenant SALAH (mismatch dari tenant_id baris yg diinsert) — **JUGA DITOLAK**, RLS bener² isolasi per-tenant, bukan cuma "asal ke-set aja lolos".

**Kesimpulan**: tool-nya siap dipakai founder buat mulai nyatat trade real. Belum dikerjakan: `shadow_pair` pairing (bag. 7 poin 4, butuh `signal_id` linkage yg emang sengaja belum ada), fidelity score, ML risk envelope — semua nunggu volume data dari tool ini.

## 20. `import_binance_position_history.py` — bulk import histori trade real founder (3 Juli 2026)

> **Verifikasi Claude Code**: founder kasih 3 export CSV Binance Futures 1 bulan penuh (Order History 838 baris, Position History 276 posisi closed, Trade History 1407 fill) — jauh lebih efisien diimpor bulk drpd satu-satu lewat `log_trade_annotation.py`. Founder catat eksplisit: sebagian trade dieksekusi dari sinyal bot sebelumnya, sebagian lain (yg profit "hingga ratusan persen") di-trade manual — dicatat di sini krn relevan ke `manual_override` (exit_reason_real), tapi **TIDAK ditebak otomatis mana yg mana** (lihat di bawah).

**Sumber & apa yg reliable diturunkan**:
- **Position History** (satu baris = satu posisi closed) — sumber utama: `Symbol`, `Margin Mode`, `Position Side`, `Entry Price`, `Avg. Close Price`, `Opened`/`Closed` map LANGSUNG ke `margin_mode`/`action`/`entry_fill_price`/`exit_fill_price`/`ts`. Semua 276 baris statusnya `Closed` (dicek langsung, bukan diasumsikan).
- **Trade History** (satu baris = satu fill/eksekusi) — dipakai HANYA utk `fees_paid_usd`: jumlahkan `Fee` tiap fill yg symbol+waktu-nya jatuh di dalam window `[Opened, Closed]` posisi terkait.
- **Order History** — **TIDAK dipakai** utk `exit_reason_real`: dicek langsung, `Type` di export founder cuma ada `{MARKET, LIMIT}`, gak ada `STOP_MARKET`/`TAKE_PROFIT_MARKET`/liquidation marker apapun yg bisa dijadiin dasar infer stop_loss/take_profit/liquidated — motor pendek order gak eksplisit kelihatan tipe apa dari data ini doang.

**Sengaja DIBIARKAN NULL, bukan ditebak**:
- `leverage` — gak ada di export Binance manapun (Position/Trade/Order History ketiganya gak punya kolom ini).
- `exit_reason_real` — alasan di atas. Termasuk trade "manual_override" yg founder sebut — gak ditebak dari besaran PnL (return gede bisa juga dari leverage tinggi kena TP normal, bukan bukti otomatis manual override).
- `funding_paid_usd` — sumbernya Binance "Income History" export terpisah, gak termasuk 3 file yg dikasih.

**Symbol coverage**: 53 simbol unik (termasuk saham/komoditas tokenized Binance: `AAPLUSDT`/`MSFTUSDT`/`MSTRUSDT`/`SPCXUSDT`/`XAUUSDT`/`XAGUSDT`/`SKHYNIXUSDT`/`ANTHROPICUSDT`/`OPENAIUSDT`) — hampir semuanya belum pernah punya baris `instrument` di DB. Tool auto-provision `Instrument` idempotent, PERSIS pola `upsert_instrument()` di `apps/products/trading/ingestion/ingest.py` (dicek baca kode-nya langsung): `Instrument.symbol == Instrument.venue_symbol == format ccxt-unified` (mis. `BTCUSDT` → `BTC/USDT:USDT`), bukan raw symbol Binance.

**Timezone**: timestamp di CSV Binance itu WAKTU LOKAL (nama file founder eksplisit `UTC7` = UTC+7/WIB), BUKAN UTC — tool terima `--tz-offset-hours` eksplisit (gak diasumsikan diam-diam), `TIMESTAMPTZ` Postgres normalize otomatis begitu offset-nya bener di input.

**10 test baru** (`test_import_binance_position_history.py`), 239 test total di `agent-orchestrator`. **Bug lama (import `sqlalchemy` level module bikin collection CI gagal) DICEGAH dari awal round ini** — modul ditulis dgn lazy import sejak awal (bukan ditemukan lewat trial-error lagi), DAN simulasi venv-fresh-persis-command-CI dijalanin SEBELUM push (bukan cuma stlh push) — 260 test lulus di simulasi persis command CI (239 + 21 backtest-core).

**Diverifikasi thd data REAL founder (bukan cuma dry-run kosong)**:
- Dry-run thd 3 file asli: 276 posisi ke-parse, 53 simbol, 1407 fill Trade History ke-load, total fee ke-match $60.62.
- **Spot-check manual 2x thd raw CSV, bukan cuma percaya output tool**: (1) posisi BTCUSDT baris#1 (entry 73645.8→73698.2) — fee ke-hitung tool `$0.073672`, dicek manual jumlah 2 fill BUY+SELL yg cocok = `0.03682290 + 0.03684910 = 0.073672` — **PERSIS SAMA**; (2) posisi STGUSDT baris#84 (32 fill, closing_pnl=-205.78, kasus multi-fill kompleks) — fee tool `$0.7464960700000001`, dicek manual jumlah 32 fill = **PERSIS SAMA**. Window-matching (symbol+waktu) kebukti bener di kasus simple MAUPUN kompleks.
- Sum total `Closing PNL` 276 posisi = **-$267.68** (net negatif sebulan penuh dari Closing PNL doang) — dicatat sbg fakta data mentah, BUKAN diinterpretasi (gak termasuk funding/fee/kemungkinan posisi kecil-vs-return-persen-nya, dan founder sendiri sebut ada campuran bot-signal vs manual trade yg profitnya beda jauh karakternya).

**SUDAH dieksekusi ke production (3 Juli 2026)** — lihat bag. 21 utk cara eksekusi (`--emit-sql` + Neon SQL Editor) dan 1 gotcha nyata yg ketemu+diselesaikan di jalan (`--tenant-email` gak bisa dipakai krn `tenant.email` founder bukan email asli).

## 21. `--emit-sql` — generate SQL manual krn Neon HTTP-SQL endpoint gak bisa multi-statement (3 Juli 2026)

> **Konteks**: sandbox Claude Code ini gak bisa konek raw Postgres port (`packages/db/migrations/env.py` butuh koneksi psycopg langsung, itu hang dari sandbox). Satu-satunya endpoint Neon yg reachable dari sini adalah HTTP-SQL (`POST .../sql` dgn header `Neon-Connection-String`) — tapi endpoint ini **cuma terima SATU statement per request** (dicek langsung: `SELECT set_config(...); SELECT current_setting(...);` dalam satu query string balikin error `{"message":"cannot insert multiple commands into a prepared statement","code":"42601"}`). `trade_annotation` pakai `FORCE ROW LEVEL SECURITY`, jadi tiap INSERT WAJIB didahului `set_config('app.tenant_id', ...)` di SESSION YANG SAMA — gak bisa dilakuin lewat endpoint yg cuma satu-statement-per-request ini.

**Solusi**: opsi baru `--emit-sql PATH` di `import_binance_position_history.py` — reuse persis logic parsing/mapping yg udah diverifikasi di bag. 20 (gak ada logic baru soal parsing CSV), tapi outputnya `.sql` file teks biasa, bukan koneksi DB langsung. Founder jalanin file ini sendiri lewat **Neon SQL Editor** (session interaktif penuh yg support multi-statement transaction, beda dari HTTP-SQL endpoint).

**Struktur file yg di-generate** (satu transaksi `BEGIN;`...`COMMIT;`, all-or-nothing):
1. `INSERT INTO instrument ... ON CONFLICT (venue_id, venue_symbol) DO NOTHING` per simbol unik — idempotent, aman dijalanin ulang.
2. `SELECT set_config('app.tenant_id', <tenant>, false)` — sekali di awal transaksi, tetap berlaku sepanjang sesi ini krn `BEGIN`/`COMMIT` yg sama.
3. `INSERT INTO trade_annotation (...)` satu baris per posisi closed (276 statement utk data real founder).

**Eksekusi ke production & 1 gotcha nyata (3 Juli 2026)**:
- Percobaan pertama pakai `--tenant-email muftiarifachrudin@gmail.com` **GAGAL** — di Neon SQL Editor muncul "Failed transaction: ROLLBACK required". Diinvestigasi: subquery `(SELECT id FROM tenant WHERE email = 'muftiarifachrudin@gmail.com')` balikin NULL krn baris `tenant` founder emailnya bukan Gmail asli, melainkan `<clerk_user_id>@unknown.clerk` — ternyata `apps/platform-core/api-gateway/deps.py` fallback ke placeholder ini (`email = claims.get("email") or f"{clerk_user_id}@unknown.clerk"`) krn JWT template Clerk gak nyertain claim `email`, dan `billing.py` copy `PlatformUser.email` apa adanya ke `Tenant.email` saat tenant dibuat. `tenant_id` yg NULL nabrak NOT NULL constraint → transaksi ROLLBACK otomatis, **gak ada satupun dari 276 baris yg kesimpen** (aman, bukan data setengah-jadi). **Implikasi**: `--tenant-email` di tool ini MAUPUN `log_trade_annotation.py` gak bisa dipakai buat akun yg emailnya belum ke-sync dari Clerk — kalau JWT template Clerk gak include claim `email`, satu-satunya cara adalah `--tenant-id` pakai UUID literal (query manual `SELECT id FROM tenant`/`platform_user` dulu). Fix di sisi Clerk dashboard (tambah claim `email` ke JWT template) BELUM dilakukan — di luar scope round ini, founder diinfokan tapi belum diminta utk act.
- Re-generate pakai `--tenant-id <uuid tenant asli founder>` (di-resolve manual lewat HTTP-SQL endpoint, query `SELECT` tunggal msh bisa lewat situ) → run ulang di Neon SQL Editor → **SUKSES**, diverifikasi founder langsung: `SELECT set_config(...); SELECT count(*) FROM trade_annotation;` balikin **276**.
- **Temuan tambahan soal HTTP-SQL endpoint**: selain field `query` (satu statement), endpoint yg sama juga terima field `queries` (array) yg mempreservasi session/context antar statement dlm SATU request (dicek: `set_config` di statement pertama, `current_setting` di statement kedua balikin nilai yg sama) — jadi utk kebutuhan verifikasi/SELECT read-only ringan, bentuk `queries` array ini cukup dari sandbox tanpa perlu Neon SQL Editor. TAPI ini beda dari kebutuhan bulk-INSERT idempotent+RLS yg tetep lebih pas lewat file `.sql` krn ukurannya (276+ statement) & krn `--emit-sql` udah reuse logic yg diverifikasi, jadi gak ganti pendekatan yg udah jalan.

`--tenant-id`/`--tenant-email` tetap jadi mutually-exclusive required group yg sama kayak jalur DB langsung — kalau yg dikasih `--tenant-email`, SQL yg di-generate pakai subquery `(SELECT id FROM tenant WHERE email = '...')`, bukan resolve ke UUID di sisi tool (krn tool ini sengaja gak konek DB sama sekali, sesuai nama opsinya).

**5 fungsi baru** (`_sql_literal`, `_tenant_id_sql`, `generate_instrument_provision_sql`, `generate_trade_annotation_insert_sql`, `generate_sql`) + 9 test baru — total 19 test di file ini, 269 test di `agent-orchestrator` + `backtest-core` gabungan. `_sql_literal` escape quote (`'` → `''`) utk semua value yg di-emit, termasuk yg berasal dari CSV (simbol/`rationale_text`), bukan cuma input manusia — defensif thd data CSV yg secara teori bisa ngandung karakter quote. Simulasi venv-fresh-persis-command-CI dijalanin sebelum push (269 test lulus, gak ada `kinetiq_db`/`sqlalchemy` ke-install, konsisten sama kebiasaan yg udah dibangun round-round sebelumnya).

**Status**: tool-nya udah lengkap+teruji, tapi **generate file SQL final dari 3 CSV real founder + eksekusi lewat Neon SQL Editor masih langkah founder sendiri** — sama kayak bag. 20, ini bukan keputusan yg diambil otomatis oleh Claude Code krn data finansial real & actionnya susah dibalik.

## 22. Deep-dive pasca run validasi pertama (2/10 window) — analisis 4 seri + derivatives, 3 Juli 2026

> **Verifikasi Claude Code**: run `run-validation.yml` #2 (BTC/USDT 1h Binance,
> 8760 candle, 10 window) GAGAL kriteria promosi bag. 7 — PF net > 1.3 cuma
> 2/10 window. Founder minta analisis mendalam: kenapa meleset, teori & skill
> apa yang dibutuhkan menuju skor 8/10, dan peran data derivatives
> (funding/OI/long-short/liquidation). Analisis penuh — replikasi 4 seri
> (BTC/ETH × Binance/Bybit, 8.763 candle 1h per seri dari `ohlcv` production),
> 2.679 trade berlabel, overlay CoinGlass 399 hari × 2 koin — ada di
> **`docs/validation-deep-dive-2026-07.md`** + summary angka mentah di
> `docs/validation-results/replication-2026-07-03.json`. Temuan kunci:
> mekanisme robust lintas bursa (Jaccard sinyal ~73%, PF per venue nyaris
> identik) tapi TIDAK generalize ke ETH (0-1/10 window); confidence score
> sekarang ANTI-prediktif (r=-0.05 — bukti empiris pertama bhw bobot
> hand-tuned menyesatkan, dan dataset 2.679 label triple-barrier round ini
> MENGHILANGKAN blocker lama Part #2); LONG rugi (PF 0.84) krn tak ada bias
> HTF (multi-timeframe PRD B.6 memang belum dibangun); band R:R 1.5-2 justru
> band terburuk; fee belum dihitung dan material (funding justru sepele utk
> holding ~11 jam); OI-fuel tereplikasi kuat deskriptif (1.8-2.7×) tapi lemah
> prediktif; positioning derivatives (funding≥p90, global L/S ekstrem,
> top-vs-global divergence, liq cascade 20/20) = sinyal contrarian kecil tapi
> konsisten 2 koin. Kombinasi dua perbaikan implementable (searah SMA200-1h +
> rr∈[2,5)) menaikkan PF pooled 0.97→1.30 gross / 1.13 net taker fee — TAPI
> in-sample, statusnya hipotesis utk diuji walk-forward, bukan hasil final.
> **Temuan non-strategi yang butuh action founder: `trade_annotation`
> production KOSONG** (pg_relation_size=0, `instrument` cuma 4 baris) padahal
> bag. 21 mencatat import 276 terverifikasi — kemungkinan transaksi Neon SQL
> Editor ter-rollback setelah verifikasi; jalankan ulang file `--emit-sql` dan
> verifikasi count dari session terpisah. Roadmap skill lengkap (fee-aware
> simulator, `htf_bias.py`, dump komponen skor per-faktor, Part #2 fitting,
> `derivatives_context.py`, backfill funding/OI native, SL anti-hunt) +
> rubric skor 3/10→10/10 yang objektif: lihat dokumen deep-dive.

> **Handoff (3 Juli 2026, sesi yang sama)**: memory investigasi lengkap +
> tabel status klaim lama dicatat permanen di
> `docs/fable5-crypto-theory-investigation-2026-07.md`; tahapan implementasi
> menyeluruh untuk sesi berikutnya (fee-aware sim → htf_bias → per-factor
> dump + fitting → derivatives_context → eksperimen R:R/SL → kampanye OOS →
> shadow trading → ekspansi universe kripto & tokenized equity → gerbang
> live) di `docs/sonnet5-implementation-roadmap.md`. Script analisis yang
> menghasilkan semua angka bag. 22 di-commit ke
> `agent-orchestrator/validation/deep_dive_2026_07/` (one-off, bukan
> production code — lihat README-nya).

## 23. `trade_simulator.py` fee-aware (Fase 1 roadmap bag. 22, F5) — DIIMPLEMENTASI 3 Juli 2026

`simulate_trade`/`simulate_trades` dapat param `fee_entry_fraction`/
`fee_exit_fraction` (aditif ke `net_return_pct` bersama funding cost, default
0.0 — perilaku lama tidak berubah kalau config tidak set fee).
`run_validation.py` jalankan `simulate_trades()` sekali lagi dengan fee
di-nol-kan (reuse hasil `generate_signals()` yang sama, tidak dobel jalan
walk O(n²)-nya) supaya PF net-funding-only bisa dipisah dari PF net-fees;
`report.py` sekarang tampilkan 3 kolom PF berdampingan (gross/net-funding/
net-fees) sesuai bag. 6 "Metrics — funding-aware". `walk_forward_windows.yaml`
default fee 0.0005/0.0005 per sisi (Binance USDT-M VIP0 taker, round-trip
0.10%, sesuai deep-dive F5). 15 test baru (332 total lulus), `ruff check`
bersih thd path yang sama dgn CI.

Verifikasi bukan cuma unit test: re-run BTC/USDT 1h Binance 1-tahun penuh
(8.764 candle, 10 window walk-forward) dgn fee live — PF gross rata-rata
antar-window ~1.10 turun ke PF net-fees ~0.92 (degradasi ~16%), arah & skala
konsisten dgn baseline deep-dive (gross ~0.97 → net-fees ~0.85). Kriteria
promosi PF (>1.3 di ≥2/3 window) TIDAK terpenuhi (1/10 window lulus) —
ekspektasi F5, bukan regresi baru: strategi baseline saat ini memang belum
profitable net-of-fees, itulah persis yang mau dibuktikan fee-aware sim ini.

Replikasi 4-seri penuh (ETH/Binance, BTC/Bybit, ETH/Bybit) belum diulang
satu-per-satu pasca perubahan fee ini — logika fee murni aritmetika per-trade
(tidak bergantung venue/simbol), jadi 1 seri BTC/Binance dianggap spot-check
yang cukup kuat, bukan pengganti replikasi penuh kalau nanti dibutuhkan bukti
lebih kuat lintas seri.

**Update Fase 0a — RESOLVED (2026-07-03, sesi yang sama)**: `trade_annotation`
production sempat dicek ulang masih `count(*)=0` di atas, TAPI itu ternyata
bukan karena transaksi gagal/rollback di database — akar masalahnya adalah
paste manual 775-baris file `--emit-sql` ke Neon SQL Editor via browser
mobile silently ter-truncate jauh di bawah ukuran file aslinya (konsisten
terpotong di baris ~140-150 terlepas dari total ukuran chunk, gejala paste
buffer/line-count limit di sisi mobile, bukan limit Neon). Setelah dipecah
jadi chunk kecil (~15-18 statement per file) dan sebagian berhasil manual
sampai row 120, sisanya (row 121-276) dieksekusi langsung dari sandbox lewat
endpoint HTTP-SQL Neon pakai bentuk `{"queries": [...]}` (lihat CLAUDE.md) —
satu request 159 query (BEGIN + set_config + 156 INSERT + COMMIT, ~90KB)
sukses penuh dalam SATU call, dikonfirmasi lewat query count terpisah
setelahnya: **`trade_annotation` = 276, `instrument` = 55**. Koreksi penting
utk memory ke depan: asumsi lama (bag. 21) bahwa bentuk `queries` array
"cuma cocok utk verifikasi ringan, bukan bulk-INSERT" ternyata SALAH dan
tidak pernah benar-benar diuji — endpoint ini terbukti sanggup menjalankan
transaksi multi-statement besar langsung dari sandbox tanpa perlu Neon SQL
Editor / paste manual founder sama sekali. Fase 0a sekarang beres, kerjaan
agreement-rate/shadow-pair bisa mulai dari data ini.

## 24. `skills/strategy/htf_bias.py` (Fase 2 roadmap, F2/F9) — DIIMPLEMENTASI 3 Juli 2026

Bagian teori founder soal bias multi-timeframe (bag. 2e: Weekly>Daily>4h>1h)
yang belum pernah diuji sama sekali sebelum ini. `resample_candles()` agregasi
1h→4h/1d kalender UTC, closed-bucket-only (bucket yang belum tutup TIDAK
ikut — dicek dari candle terakhir bucket itu sendiri, bukan hitung
expected-count, biar toleran thd input yang berhenti di tengah bucket).
`compute_bias()` REUSE `market_structure.trend_bias()` di atas swing hasil
resample — bukan detektor tren baru, satu sumber kebenaran sama pola
`market_structure.py` sendiri. `htf_alignment_score()` — faktor skor (BUKAN
gate) 0-1, renormalize timeframe yang hadir mirip
`confluence_across_timeframes()`, 0.15 (bukan 0) kalau berlawanan arah.
`sma_trend_bias()` proxy close-vs-SMA(200) sengaja dibiarkan TERPISAH, jadi
kandidat independen utk fitting Fase 3 (bukan di-blend duluan) — sesuai
temuan F9 deep-dive bhw SMA-alignment yang tervalidasi kausal, bukan
trend_bias berbasis swing per se.

`ConfluenceWeights` dapat slot baru `htf_alignment=0.10` (0.05 diambil dari
`swing_quality`), `score_confluence()` dapat parameter `htf_alignment` (default
neutral 1.0 sama pola `regime_alignment`), `signal_runner.generate_signals()`
hitung Daily+4h bias tiap bar dari `candles[:i+1]` (anti-lookahead) dan wire
sebagai slot terpisah dari `regime_alignment` (structure BOS/CHoCH ≠ HTF
trend, dua sinyal berbeda, tidak dicampur). 21 test baru, 330 test total
lulus, `ruff check` bersih.

**Diverifikasi thd data real** (BTC/USDT 1h Binance, full 1 tahun): decline
10-hari tertajam di seluruh data (28.8%, berakhir 2026-02-05) correctly
teridentifikasi `DOWNTREND` di Daily DAN 4h — `htf_alignment_score` utk
sinyal SHORT di titik itu 1.000 (aligned), LONG 0.150 (opposed), persis
sesuai ekspektasi. Funnel diagnostic tidak berubah: 6 sinyal dari fixture
`noisy_zigzag()` (seed=42) tetap 6 sebelum/sesudah — `htf_alignment` cuma
memodulasi nilai confidence, tidak pernah menggagalkan sinyal. Detail
implementasi lengkap: `docs/sonnet5-implementation-roadmap.md` Fase 2.

## 25. Dump per-faktor + Part #2 fitting (Fase 3 roadmap, F1) — DIIMPLEMENTASI 3 Juli 2026, hasil: BELUM DIADOPSI (temuan valid, bukan kegagalan)

Bagian yang mengubah confidence scoring dari opini (bobot hand-tuned) jadi
sains (fitting thd outcome triple-barrier real). `signal_runner.Signal`
dapat 7 field per-faktor baru — semua default `0.5` biar ADITIF murni,
2 test lama yg konstruksi `Signal` langsung (`test_shadow_pair.py`,
`test_trade_simulator.py`) TIDAK perlu disentuh sama sekali. Modul baru
`validation/fib_gann_backtest/fit_weights.py`: `LogisticRegression
(solver="saga", l1_ratio=0.5)` (elastic-net L1+L2 satu fit, bukan dua model
terpisah), **refit PER window walk-forward** (train di train-range, evaluasi
HANYA di test-range — bukan sekali di seluruh tahun, itu persis kesalahan yg
bikin temuan F10 deep-dive cuma berstatus hipotesis in-sample). Dua skema
label dilaporkan sesuai brief: binary (TAKE_PROFIT=1/STOP_LOSS=0, TIMEOUT
dikecualikan total) dan 3-kelas (`BarrierOutcome` +1/-1/0 langsung jadi
label). Trade `censored` dikecualikan dari kedua skema — outcome-nya belum
genuinely diketahui, bukan TIMEOUT asli. `regime_alignment` SENGAJA
dikeluarkan dari fitur yg di-fit (nilainya identik `structure_alignment` di
wiring sekarang — collinearity sempurna tanpa nilai tambah).
`scikit-learn`/`numpy` cuma masuk `packages/backtest-core[dev]` (CI `test`
job doang), TIDAK PERNAH masuk `requirements.txt` root maupun
`apps/products/trading/ingestion/requirements.txt` yg dipakai servis
production beneran. 25 test baru, 355 test total lulus, ruff clean.

**Kriteria adopsi (bag. 3c roadmap): AUC OOS median > 0.55 DAN korelasi
confidence-vs-return OOS > 0.** Hasil real thd BTC/USDT 1h Binance (10
window walk-forward, bukan cuma unit test): skema binary 6-faktor primer —
median AUC OOS **0.522**, korelasi pooled (367 sampel OOS) **+0.018**.
**TIDAK diadopsi** — AUC median di bawah ambang 0.55, meski korelasinya
sudah POSITIF (perbaikan nyata drpd baseline hand-tuned lama F1 yg
r=-0.05, walau masih sangat lemah). Sesuai prinsip "kalau tidak tercapai,
laporkan jangan paksakan" — `ConfluenceWeights` default TIDAK diganti round
ini.

**Temuan sampingan (kolom kandidat `sma_trend_bias_alignment`) yg justru
paling penting round ini**: sesuai arahan founder eksplisit, Fase 2's
`htf_bias.sma_trend_bias()` (proxy close-vs-SMA200, sengaja TIDAK di-blend
ke `htf_alignment` sejak Fase 2) di-dump jadi kolom kandidat terpisah dan
di-fit sbg varian ke-3 (`binary_with_sma_candidate`, 6 faktor primer + kolom
ini) — murni informational, TIDAK ikut kriteria adopsi resmi. Hasilnya:
median AUC naik ke **0.617** (dari 0.522), dan `sma_trend_bias_alignment`
dapat koefisien BUKAN-NOL di **SEMUA 10 dari 10 window** (rentang
0.164-1.448) — sedangkan `htf_alignment` (basis swing, yg sekarang
benerannya di-wire ke confidence via Fase 2) di-nolkan L1 di beberapa window
atau turun jauh begitu kandidat SMA ikut di-fit bareng. Ini **konsisten
persis** dengan temuan F9 deep-dive (SMA50/200-alignment yg tervalidasi
kausal, bukan trend_bias berbasis swing) — tapi ini baru 1 sinyal dari
fitting kandidat round ini, bukan kriteria adopsi resmi yg tetap dievaluasi
di skema 6-faktor primer sesuai instruksi founder "kriteria adopsi tetap".
**Belum diadopsi/di-wire ke `htf_alignment_score` round ini** — dicatat sbg
kandidat kuat utk direvisit (mis. ganti/tambah `sma_trend_bias_alignment`
jadi slot resmi `ConfluenceWeights`, atau bagian eksperimen Fase 6 kampanye
OOS berikutnya), bukan keputusan yg diambil sepihak sekarang. Detail penuh:
`docs/sonnet5-implementation-roadmap.md` Fase 3.
