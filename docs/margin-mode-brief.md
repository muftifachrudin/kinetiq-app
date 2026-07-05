# Brief: Margin Mode (Cross vs Isolated), Margin Ratio, dan PreTradeCard

Keputusan desain + spec implementasi hasil diskusi founder ↔ Fable 5
(3 Juli 2026), menyambung `docs/shadow-simulator-brief.md` (leverage/
liquidation-aware sim, bag. 2 & 5) dan `docs/sonnet5-implementation-roadmap.md`
(F7a/F7b menunjuk ke dokumen ini). Konteks pengalaman founder yang memicu
brief ini: margin ratio adalah metrik pengikat antara mode margin, size,
initial margin, dan leverage — dan sinyal seharusnya memberi **data
pra-eksekusi** (berapa initial margin, berapa leverage) sebelum entry,
karena keduanya menentukan persentase TP, jarak aman SL, dan seberapa besar
momentum bisa dimonetisasi.

## 1. KEPUTUSAN: margin mode ditentukan di level mandate, bukan per-trade — dan MVP default ISOLATED

**Margin mode wajib ditentukan pengguna DI AWAL (onboarding → `risk_mandate`),
bukan dipilih ulang setiap sinyal.** Alasannya konsekuensi arsitektur yang
sudah kita bangun, bukan selera:

1. **Konsisten dengan prinsip yang sudah dikunci** (shadow-brief bag. 5):
   leverage adalah OUTPUT dari struktur trade (`risk_amount = equity ×
   risk_pct` → `qty = risk_amount / |entry − SL|` → `leverage_used =
   min(diminta, max_safe_leverage)`), bukan input yang dimaksimalkan. Margin
   mode adalah bagian dari struktur risiko yang sama. Kalau jadi tombol
   per-trade, kita menambah satu degree of freedom hand-tuned baru — persis
   kelas kesalahan yang temuan F1 deep-dive (confidence anti-prediktif)
   buktikan mahal — dan data shadow-pair jadi tidak bisa dibandingkan antar
   trade.
2. **Hanya isolated yang liquidation price-nya deterministik SAAT SINYAL
   TERBIT**, tanpa tahu state seluruh akun. Cross butuh total equity +
   unrealized PnL semua posisi lain, dan est. liquidasinya bergeser setiap
   posisi lain bergerak. `trade_simulator.MarginContext` sudah jujur soal
   ini: cross hanya diwakili `cross_buffer_pct` yang disuplai caller, karena
   simulator per-sinyal memang tidak punya state portfolio.
3. **Shadow-pair attribution bersih hanya di isolated**: `size_leverage_
   effect` per posisi terisolasi dari posisi lain. Di cross, nasib satu
   posisi tercemar posisi lain yang tidak ada hubungannya dengan sinyalnya —
   dekomposisi divergence (inti fase shadow) jadi tidak bisa dipercaya.
4. **Kartu pra-eksekusi yang founder minta hanya bisa FINAL di isolated**:
   initial margin, leverage, est. liq price bisa dihitung dan tetap benar
   sampai posisi ditutup. Di cross, angka itu estimasi yang kedaluwarsa
   begitu posisi lain bergerak — tetap boleh ditampilkan nanti, tapi wajib
   berlabel "estimasi, bergantung posisi lain".

**Cross TIDAK ditolak permanen** — dia masuk F7b (portfolio-level margin
simulator) SETELAH shadow loop punya state posisi nyata. Sama polanya
seperti parallel-channel (brief utama bag. 2c): ditunda sadar, bukan
dibuang.

## 2. Koreksi mekanik (supaya tidak terbawa salah ke spec)

Dari pesan founder: "isolated menambah entri lebih dari 1 akan mengurangi
nilai est. liquidasi keseluruhan" — mekaniknya benar, labelnya tertukar:

- **Isolated murni**: posisi tambahan TIDAK mengubah liquidation price
  posisi lain (justru itu fitur utamanya). Yang berubah adalah **saldo
  bebas** (available balance) untuk margin posisi berikutnya.
- **Cross**: inilah mode di mana entri tambahan menggeser est. liquidasi
  KESELURUHAN — semua posisi berbagi satu kolam margin, satu posisi rugi
  besar menarik liq price semua posisi mendekat.

Pembedaan ini yang harus muncul eksplisit di PreTradeCard (bag. 4) dan di
copy UI onboarding nanti.

## 3. Margin ratio — di mana dia hidup di sistem kita

- **Isolated (sekarang)**: margin ratio per-posisi ≈ fungsi jarak harga ke
  liq price posisi itu sendiri. Sudah tercakup secara implisit oleh
  invariant yang di-enforce `assert_liquidation_safe()`:
  `liquidation_price` harus lebih jauh dari SL struktural + buffer_k×ATR.
  PreTradeCard menampilkannya sebagai angka informatif, bukan gate baru.
- **Cross (F7b nanti)**: margin ratio jadi metrik AKUN
  (maintenance margin total / margin balance; liquidasi saat mendekati
  100%). Guardrail-nya sudah dicadangkan shadow-brief bag. 5: "total margin
  used / equity ≤ X% per regime (X dipelajari dalam range 20-60%)" — itu
  baru bisa hidup saat ada state posisi nyata (F7), dan telemetry
  margin-ratio akun + kill-switch adalah bagian F7b.
- **Konteks derivatives menyambung ke sini**: temuan liq-cascade 20/20
  (deep-dive F7) adalah alasan empiris kenapa `derivatives_context` (F4)
  boleh MENURUNKAN size/melebarkan buffer di hari high-vol — tapi tidak
  pernah menaikkan leverage di atas cap. Arah pengaruhnya satu arah:
  konservatif saja.

## 4. Spec `skills/strategy/position_sizing.py` + PreTradeCard (untuk Sonnet 5 — roadmap F7a)

Pure-function skill, TANPA DB, disiplin yang sama seperti `shadow_pair.py`/
`trade_simulator.py`. Boleh dikerjakan kapan saja, paralel dengan fase lain
— prasyarat nyata untuk shadow loop (F7) dan Telegram surfacing.

**Input** (semua eksplisit, tidak ada global):
- dari sinyal: `direction`, `entry_price`, `stop_loss`, `take_profits`
  (ExitPlan yang sudah ada), `atr_value`
- dari mandate: `equity`, `risk_pct_per_trade`, `margin_mode`
  (MVP: terima dua nilai tapi cross → raise `NotImplementedError` dengan
  pesan menunjuk F7b — JANGAN pura-pura menghitung), `max_leverage_cap`
  (hard cap manual per simbol/kelas aset — daftar "TIDAK BOLEH dipelajari
  ML"), `maintenance_margin_rate`, `buffer_k`
- opsional dari `derivatives_context` (F4, kalau tersedia): flag high-vol
  (`fuel_quadrant`/`liq_cascade`) → pengaruh SATU ARAH: perkecil
  `risk_pct` efektif / perlebar buffer, tidak pernah sebaliknya.

**Output — `PreTradeCard` (frozen dataclass)**, jawaban langsung untuk dua
pertanyaan pra-eksekusi founder:
- `risk_amount_usd` = equity × risk_pct efektif
- `qty` = risk_amount / |entry − SL| ; `notional_usd` = qty × entry
- `max_safe_leverage` (reuse fungsi yang SUDAH ADA di `trade_simulator.py`,
  jangan tulis ulang)
- `leverage_used` = min(`max_leverage_cap`, `max_safe_leverage`) —
  **initial margin & leverage adalah OUTPUT kartu ini, bukan input user**
- `initial_margin_usd` = notional / leverage_used
- `est_liquidation_price` (reuse `build_margin_context()`)
- `margin_ratio_at_entry` (informatif)
- `sl_distance_pct_notional`, `tp1_distance_pct_notional`, DAN versi
  margin-leveraged (`× leverage_used`) — dua-duanya, supaya "persentase TP
  dan jarak aman SL" terbaca di kedua skala (pelajaran bag. 13 brief utama:
  margin_return bisa -50% dari notional -1.5%)
- `warnings: tuple[str, ...]` — minimal: `max_safe_leverage < cap`
  (struktur trade yang membatasi, bukan cap), liq-distance mendekati
  invariant, initial_margin > saldo bebas yang disuplai caller.

**Invariant fail-fast** (bukan warning): `assert_liquidation_safe()` yang
sudah ada tetap dipanggil; kartu TIDAK terbit untuk kombinasi yang
melanggarnya.

**Acceptance**:
- Unit test angka eksak (kasus LONG & SHORT; leverage terpotong cap vs
  terpotong max_safe; cross → NotImplementedError).
- Spot-check terhadap ≥1 sinyal real BTC/USDT 1h production (pola verifikasi
  standar semua skill), angkanya ditulis di brief.
- TIDAK menyentuh `signal_runner`/gate manapun — kartu dihitung SETELAH
  sinyal lolos gate, murni lapisan presentasi+sizing.

**Status: SELESAI (3 Juli 2026, hari yg sama).** `skills/strategy/
position_sizing.py` diimplementasi persis spec di atas: `PreTradeCard`
(frozen dataclass), `build_pre_trade_card()` reuse `max_safe_leverage()`/
`build_margin_context()`/`assert_liquidation_safe()` dari `trade_simulator.py`
tanpa ditulis ulang, `margin_mode=CROSS` raise `CrossMarginNotImplementedError`
(subclass `NotImplementedError`) menunjuk F7b, `derivatives_context` high-vol
flag cuma mengecilkan `risk_pct` efektif (tidak pernah menaikkan leverage/cap).
11 test baru (`tests/test_position_sizing.py`), 322 test total (agent-
orchestrator, di luar `test_fit_weights.py` yg butuh numpy/scikit-learn CI-
only) lulus, ruff clean.

**Spot-check thd data real BTC/USDT 1h production** (250 candle terakhir s/d
2026-07-03T18:00Z, instrument_id=1 Binance, ditarik via Neon HTTP-SQL endpoint
langsung dari sandbox): swing terakhir terdeteksi LOW @ 61113.80 (idx=223,
2026-07-02T16:00Z), basis leg HIGH @ 62180.00 (idx=221). Sinyal LONG di entry
62180.30 (close bar terakhir) menghasilkan `ExitPlan` SL=60916.21, TP1=62621.41
(R:R=0.35 — di bawah gate R:R production, tapi itu tanggung jawab
`passes_risk_reward_gate()` yg memang tidak disentuh modul ini, bukan bug di
sini). `build_pre_trade_card()` dgn `equity_usd=10000`, `risk_pct_per_trade=
0.01`, `max_leverage_cap=3.0` (default mandate): `max_safe_leverage=30.48x`
(struktur SL/ATR-nya jauh lebih longgar dari cap), `leverage_used=3.0x` (cap
mandate yg mengikat, bukan struktur — makanya tidak ada warning "below cap"),
`qty=0.0791`, `notional_usd=4918.99`, `initial_margin_usd=1639.66`,
`est_liquidation_price=41702.25`, `sl_distance_pct_notional=2.03%` vs
`sl_distance_pct_margin=6.10%` (persis pola bag. 13 brief utama: jarak SL
kelihatan kecil di notional, jauh lebih besar diukur thd margin) — semua
angka konsisten & lolos invariant `assert_liquidation_safe()` tanpa perlu
override.

Skema DB `risk_mandate.default_margin_mode` + `risk_pct_per_trade` (bag. 5)
dibuat via migrasi `packages/db/migrations/versions/
0007_risk_mandate_margin_mode_columns.py` (bukan "dititipkan" ke PR draft
Fase 0d spt rencana awal — PR itu sudah merge & dieksekusi produksi duluan,
lihat catatan di file migrasi). Diverifikasi end-to-end thd Postgres 16 lokal
sekali pakai (bukan cuma dibaca): full chain `alembic upgrade head` (0001→
0007) sukses, `\d risk_mandate` konfirmasi kolom+CHECK constraint persis
sesuai spec, `alembic downgrade -1` bersih (kolom hilang, constraint hilang),
upgrade ulang sukses lagi. `packages/db/migrations/` kena CODEOWNERS — PR ini
tetap butuh review manual founder sebelum merge, sama seperti Fase 0d.

## 5. Onboarding prasyarat: trading style → `risk_mandate`

Jawaban untuk "apakah wajib ditentukan pengguna di awal": **ya**, lewat
kuesioner singkat onboarding yang menghasilkan mandate (bukan pilihan bebas
per-trade):

| Pertanyaan ke user | Field mandate | MVP |
|---|---|---|
| Mode margin | `default_margin_mode` | `isolated` (cross tampil sebagai "coming soon" — jangan disembunyikan, jelaskan kenapa) |
| Risiko per trade | `risk_pct_per_trade` | pilihan 0.5% / 1% / 2%, hard cap 2% |
| Leverage maksimum | `max_leverage` (kolom sudah ada) | default 3x, cap manual per kelas aset |
| Posisi bersamaan maks | `max_concurrent_positions` | angka kecil (mis. 3) |
| (F7b) plafon margin ratio akun | `account_margin_ratio_cap` | belum — butuh state portfolio |

Status kolom di `risk_mandate` per hari ini (diverifikasi langsung ke
`packages/db/src/kinetiq_db/models.py`): `max_leverage` (Numeric, default 3),
`max_position_notional_usd`, `max_daily_loss_usd`, `max_drawdown_pct`,
`kill_switch_active` SUDAH ADA. Yang BARU untuk MVP kartu ini:
`default_margin_mode` (Text, CHECK `in ('cross','isolated')`, server_default
`'isolated'`) dan `risk_pct_per_trade` (Numeric(5,4), server_default `0.01`,
hard cap 0.02 di-enforce aplikasi). `max_concurrent_positions` dan
`account_margin_ratio_cap` DITUNDA ke F7b — jangan ditambah sebelum ada
yang memakainya. **CODEOWNERS path — titipkan kolom baru ini di PR draft
Fase 0d** yang memang sudah menyentuh area migration, supaya satu kali
review founder.

## 6. Yang SENGAJA belum diputuskan / ditunda (jangan diimplementasi diam-diam)

- **Cross portfolio simulator, est. liq akun, margin-ratio telemetry akun +
  kill-switch** → F7b, setelah shadow loop punya posisi nyata.
- **Pyramiding / multi-entry per sinyal**: MVP tetap satu sinyal = satu
  posisi isolated, supaya data kalibrasi bersih. Multi-entry (dan efeknya
  ke liq — mekanik cross yang founder deskripsikan) masuk F7b sebagai
  fitur yang diuji dengan disiplin yang sama, bukan default.
- **ML apapun di sizing**: tetap tunduk cold-start rule shadow-brief bag. 5
  (≥50 pasangan; hard cap/kill-switch/floor buffer_k TIDAK PERNAH
  dipelajari ML).

## 7. Margin envelope: formula 3-faktor + ambang min/max (riset empiris Fable 5, 5 Juli 2026)

Menjawab pengalaman founder dengan uang nyata: "PF net sangat bergantung
pada margin ratio, initial margin, dan leverage — semakin kecil semakin
baik." **Pengalaman itu BENAR, dan sekarang terukur persis DI MANA
benarnya** — direplay terhadap 622 trade stack (aligned & rr[2,5), exit
terbaik per aset F13, fee maker) dengan mekanika liquidation-before-SL
(isolated, MMR flat 0.4%): script `validation/deep_dive_2026_07/
lev_curve.py`.

**Temuan kunci — kurva PF-margin vs leverage:**

| Leverage | PF margin | % trade ter-liquidasi |
|---|---|---|
| 2× – 20× | **1.309 (FLAT sempurna)** | 0.0% |
| 25× | 1.282 | 0.5% (liquidation pertama muncul) |
| 40× | 1.215 | 6.1% |
| 50× | 1.123 | 14.6% |

Distribusi `max_safe_leverage` per-trade (buffer 1×ATR): p05 = 22×,
p50 = 42×, p95 = 82×. Interpretasi yang mendamaikan pengalaman founder
dengan matematika sizing risk-first:

1. Dalam sizing kita (notional ditentukan risk_pct & jarak SL DULUAN),
   leverage TIDAK menyentuh PF sama sekali selama liq price di luar
   SL+buffer — dia hanya dial "berapa equity terkunci sbg IM".
2. PF baru runtuh saat leverage menembus `max_safe` per-trade — dan
   onset empirisnya ~22-25× di data kita. "Semakin kecil semakin baik"
   = benar sebagai aturan aman; presisinya: **tidak ada MANFAAT PF
   apa pun di atas ~20×, hanya tail-risk** — dan mean return per margin
   yang terus naik s/d 40× adalah jebakan psikologis yang menjelaskan
   kenapa akun real dgn leverage tinggi terasa "makin untung" sampai
   tiba-tiba mati.
3. Kanal ketiga pengaruh 3 faktor ini ke PF real adalah PERILAKU
   (margin ratio akun tinggi → panik/deleverage paksa/manual override)
   — tidak terlihat di backtest mana pun, diukurnya lewat shadow-pair
   `size_leverage_effect`/`manual_override` (F7 Tahap 2).

**Status: WIRED ke `position_sizing.py` (5 Juli 2026, follow-up sesi yang
sama).** `η`/`L_onset` di-implementasi persis sebagai `ETA_SAFETY_FACTOR`
(0.5) dan `LEVERAGE_ONSET_CEILING` (20.0) -- `leverage_used = min(
max_leverage_cap, ETA_SAFETY_FACTOR * max_safe_leverage,
LEVERAGE_ONSET_CEILING)`, ganti formula lama `min(max_leverage_cap,
max_safe_leverage)` yang belum menerapkan kedua faktor ini. `max_safe_
leverage` field pada `PreTradeCard` tetap nilai mentah (properti
struktural tanpa η/ceiling) utk diagnostik; hanya `leverage_used` yang
menerapkan envelope penuh. Pesan warning dibedakan: SL/ATR (dikali η) vs
ceiling 20× empiris, mana pun yang jadi pembatas. 1 test baru (ceiling
mengikat saat SL/ATR sangat rapat), 2 test lama diupdate angkanya (η
membelah leverage_used yg tadinya cuma dibatasi struktur), 465 test
agent-orchestrator total lulus, ruff clean.

**Formula envelope (perluasan rantai F7a `position_sizing.py`):**

```
R_pct      = |entry − SL| / entry                 # dari struktur (F5: SL 1.0×ATR)
notional   = equity × risk_pct / R_pct            # risk-first, BUKAN margin-first
L_safe     = max_safe_leverage(entry, SL, ATR)    # sudah ada di trade_simulator
L_used     = clamp(L_request, 1, min(cap_aset, η·L_safe, L_onset))
             # η = 0.5 (safety utk gap/wick); L_onset = 20 (empiris, kurva di atas)
IM         = notional / L_used
MR_posisi  = MMR × L_used                         # aproksimasi isolated saat entry
MR_akun    = Σ IM_posisi_terbuka / equity
```

**Ambang min/max (mandate defaults, era shadow):**

| Faktor | Min | Max (soft) | Max (hard) | Dasar |
|---|---|---|---|---|
| `risk_pct_per_trade` | 0.25% (di bawah ini min-notional venue & pembulatan qty mendistorsi) | 1% | 2% | shadow-brief bag. 5 |
| `leverage` | 1× | 3× (default mandate) | min(cap kelas aset 5-10×, 0.5×`L_safe`, **20× ceiling empiris**) | kurva di atas + `assert_liquidation_safe` fail-fast |
| `initial_margin` per posisi | — | 5% equity | 10% equity | kalau IM > cap → turunkan risk_pct, BUKAN naikkan leverage |
| `MR_posisi` saat entry | — | ≤2% | ≤8% (≈ MMR×20) | konsekuensi L_onset |
| `MR_akun` (Σ IM/equity) | — | 30% | 40% (blokir entry baru) | shadow-brief band 20-60%, ambil sisi konservatif |

**Keterkaitan F0-F6 ke formula ini** (kenapa tiap fase menyumbang):
F1 (fee-aware) menentukan biaya per unit notional yang dikalikan L di
skala margin; F5 (SL 1.0×ATR) melebarkan R_pct → menurunkan L_safe per
trade → ceiling makin mengikat (SL lebar = wajib leverage lebih rendah,
BUKAN pilihan); F2/#82 (gate alignment) & F3 (fitting) menentukan trade
mana yang ADA di kurva; F4 (derivatives) memodulasi SATU ARAH konservatif
(hari liq-cascade/fuel → η turun atau risk_pct turun); F0c (funding
native) melengkapi erosi cushion utk holding panjang; F6 (kampanye)
adalah tempat semua konstanta di tabel diuji OOS sebelum jadi default
mandate.

## 8. S/R per timeframe → berapa lama trade boleh hidup (klaim founder, spec uji I7)

Klaim founder: 3 faktor margin tidak berguna tanpa tahu area support/
resistance per timeframe — dan **timeframe tempat S/R itu terbentuk
menentukan berapa lama trade dibiarkan berjalan**. Ini konsisten dengan
dua hal yang sudah ada: `level_strength.py` (bobot kekuatan level per
timeframe — teori founder yang sudah diimplementasi Part #1) dan temuan
exit-lab (timeout 20-bar flat @1h adalah aturan buta-timeframe satu-
satunya yang tersisa di exit path).

**Hipotesis I7 (pre-registered untuk harness):** `max_holding_bars`
proporsional terhadap timeframe ANCHOR level yang memicu sinyal, bukan
konstanta: level dari struktur Daily diberi napas lebih panjang (mis.
timeout = k × durasi-bar swing basis, k di-A/B {1.0, 1.5, 2.0}), level
intraday 1h tetap pendek. Prasyarat: multi-TF anchor belum ada di
signal_runner (masih single-TF 1h) — versi proxy yang bisa diuji
SEKARANG: skala timeout dgn durasi swing basis (`pivot.index −
basis_leg_start.index`), data yang sudah dicatat di setiap Signal.
Aturan disiplin tetap: faktor skor/parameter exit, BUKAN gate baru;
uji walk-forward net-of-fees; lapor juga kalau hasilnya nol (timeout
flat ternyata cukup — itu juga temuan).
