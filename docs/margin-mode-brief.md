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
