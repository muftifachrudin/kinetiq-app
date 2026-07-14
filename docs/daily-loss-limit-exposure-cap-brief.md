# Brief: Daily-Loss-Limit / Drawdown Kill-Switch & Exposure Cap (Risk Hard Gate, sub-gate 4)

Desain (bukan implementasi) untuk sisa terakhir "exposure caps" ENGGANG
Layer 3 yang ditandai `docs/kanban.md`/`docs/prd.md` sebagai belum ada
desain sama sekali: daily-loss-limit, kill-switch drawdown otomatis, dan
correlation-based exposure cap. Mengikuti konvensi proyek ini — brief
dulu sebelum kode (`docs/margin-mode-brief.md`,
`docs/regime-gate-knn-risk-memory-brief.md`) — dokumen ini TIDAK
mengubah kode maupun skema DB apa pun.

## Konteks

Berbeda dari brief regime-gate/kNN (14 Juli 2026) — di situ ALGORITMA-nya
yang belum ada, tapi data mentahnya (OHLCV, 2.679 trade berlabel) sudah
berlimpah — riset untuk brief ini menemukan sesuatu yang lebih mendasar:
**model data-nya sendiri belum punya konsep running-PnL sama sekali**.

- `Position` tidak punya kolom PnL/harga-mark/status-terbuka apa pun —
  cuma `entry_price`, "terbuka" disimpulkan secara implisit dari
  `closed_at IS NULL` (bukan flag eksplisit), dan **tidak ada `exit_price`
  sama sekali** — jadi realized PnL secara harfiah tidak bisa dihitung
  hari ini, bahkan secara retroaktif.
- `OrderAuditLog` punya `payload` JSONB yang tidak terdokumentasi
  bentuknya dan tidak pernah ditulis kode apa pun.
- Tidak ada orkestrator live sama sekali — `execution/custody/` dan
  `agent-orchestrator/graphs/` masih `.gitkeep` kosong — jadi tidak ada
  yang bisa memberi gate ini state posisi nyata bahkan kalau gate-nya
  sudah didesain.

Kabar baiknya: `RiskMandate.max_daily_loss_usd`/`max_drawdown_pct`
**sudah ada sebagai kolom DB sejak migrasi 0001** (migrasi paling
pertama) — cuma tidak pernah dibaca/ditulis kode apa pun sama sekali.
`execution/risk_gate.py`'s `RiskMandateSnapshot` sendiri bahkan belum
membawa 2 field ini.

Brief ini sengaja dipersempit: hanya mendesain 2 bagian yang secara
konsep sederhana dan cuma butuh fondasi data (daily loss, kill-switch
drawdown — keduanya menurut prinsip eksplisit `docs/shadow-simulator-
brief.md` §5 WAJIB hard-coded, tidak pernah dipelajari ML, jadi tidak
ada algoritma baru yang perlu diciptakan, cuma pipa datanya). Brief ini
sengaja TIDAK mengarang metodologi "correlation-based" dari nol — tidak
ada desain apa pun di dokumen manapun soal apa yang dimaksud "korelasi"
di sini (return? arah? overlap notional per kelas aset?). Sebagai
gantinya, brief ini mengusulkan reuse formula margin-ratio-cap akun yang
SUDAH ADA di `docs/margin-mode-brief.md` §7 sebagai gate exposure agregat
v1, dan menyisakan correlation-based capping yang sesungguhnya sebagai
item terpisah untuk sesi desain lain — disiplin yang sama dengan
"jangan mengarang algoritma untuk gate safety-critical" yang sudah
dipakai brief regime-gate/kNN.

**Hasil brief ini**: desain docs-only, BUKAN migrasi/kode — implementasi
adalah sesi terpisah, karena butuh migrasi skema nyata (path
CODEOWNERS-protected, wajib review founder) dan toh belum ada orkestrator
live untuk disambungkan sama sekali.

## 1. Definisi running-PnL: realized + unrealized dari data yang sudah ada

**Running PnL = realized (dari posisi yang sudah ditutup) + unrealized
(posisi terbuka di-mark ke harga close OHLCV terbaru)**. Unrealized PnL
TIDAK butuh live price feed baru — `ohlcv` sudah terus-menerus diisi
ingestion worker (Coolify), jadi "harga sekarang" untuk instrumen apa pun
tinggal baris `ohlcv` terbaru. Ini menghindari membangun infrastruktur
baru untuk sesuatu yang sudah ada.

## 2. Penambahan skema minimal (untuk sesi implementasi nanti, BUKAN dibangun di brief ini)

- `position`: tambah `status` (Text, CHECK `in ('open','closed')`) —
  mengganti konvensi rapuh "`closed_at IS NULL` berarti terbuka" dengan
  flag eksplisit; tambah `exit_price` (Numeric(24,10), nullable) dan
  `realized_pnl_usd` (Numeric(24,4), nullable) diisi saat posisi ditutup.
  `Position` saat ini SAMA SEKALI tidak punya harga keluar, jadi realized
  PnL secara harfiah tidak bisa dihitung bahkan setelah kejadian.
- Tabel baru `equity_snapshot` (`account_id`, `ts`, `equity_usd`,
  `realized_pnl_usd`, `unrealized_pnl_usd`) — ledger periodik (ditulis
  proses mana pun yang nanti memegang eksekusi live, cadence serupa pola
  Coolify Scheduled Task yang sudah dipakai migration-runner). Ini jadi
  sumber kebenaran untuk "equity di awal hari ini" dan "equity puncak
  sepanjang masa" — menghitung ulang dari histori posisi mentah tiap kali
  gate dicek akan mahal dan rapuh; ledger snapshot adalah pola standar
  (alasan yang sama dengan kenapa `docs/shadow-simulator-brief.md` tidak
  menghitung ulang state shadow-pair dari nol tiap kali).

## 3. Dua formula hard-coded, tanpa ML, reuse kolom RiskMandate yang sudah ada

- **Daily loss limit**: `equity_at_start_of_day_usd - current_equity_usd
  >= mandate.max_daily_loss_usd` → tolak trade baru untuk sisa hari
  kalender UTC itu (tidak menutup posisi yang sudah terbuka).
- **Drawdown kill-switch**: `(peak_equity_ever_usd - current_equity_usd)
  / peak_equity_ever_usd >= mandate.max_drawdown_pct` → flatten semua
  posisi terbuka DAN set `kill_switch_active=True` (reuse jalur
  enforcement kill-switch manual yang SUDAH ADA di `risk_gate.py` v1 —
  ini cara BARU untuk sampai ke state yang sama, bukan mekanisme
  enforcement baru).

## 4. Pertanyaan terbuka yang sengaja TIDAK dijawab brief ini

`RiskMandate.max_drawdown_pct` default DB-nya `0.15` (15%), tapi
`docs/prd.md`'s tabel exit-gate Fase 4 bilang "DD 20% → auto-flat" dan
Ringkasan Eksekutif bilang "hard stop di 20%". Brief ini tidak diam-diam
memilih salah satu — ini dicatat eksplisit untuk diputuskan founder saat
implementasi mulai (mungkin memang disengaja: 15% untuk tahap shadow/
canary, 20% untuk tahap berikutnya, tapi tidak ada dokumen yang bilang
begitu juga).

## 5. Exposure cap v1 = reuse formula margin-ratio-cap yang sudah ada

Bukan metodologi korelasi baru: `Σ initial_margin_usd(posisi terbuka) /
equity_usd`, ambang 30% soft-warning / 40% hard-block (angka
`margin-mode-brief.md` sendiri, bukan dikarang di sini). Ini mencapai
tujuan yang sama dengan yang diisyaratkan kata "korelasi" di PRD —
mencegah risiko terkonsentrasi bersembunyi di balik banyak posisi kecil
— tanpa mengarang ukuran statistik korelasi yang belum tervalidasi.
Korelasi return/harga sungguhan antar instrumen tetap eksplisit DI LUAR
scope — sesi desain terpisah di masa depan, begitu ada cukup histori
multi-posisi nyata untuk membuat ukuran korelasi bermakna sama sekali
(saat ini histori posisi live nyata masih nol).

## 6. Bentuk ekstensi `execution/risk_gate.py` (untuk sesi implementasi nanti)

Field baru di `RiskMandateSnapshot` (`max_daily_loss_usd: float | None`,
`max_drawdown_pct: float | None`, `max_margin_ratio: float | None`) dan
input baru yang disuplai caller ke `evaluate_risk_gate()`
(`current_equity_usd`, `equity_at_start_of_day_usd`,
`peak_equity_ever_usd`, `current_margin_ratio` — semua float polos,
DB-free, sama persis pola yang sudah ada). Tidak ada perubahan pada
disiplin inti modul (kumpulkan semua rejection, pure function).

## Yang eksplisit TIDAK termasuk brief ini

- Kode atau migrasi apa pun — ini dokumen desain saja, sama seperti
  `docs/regime-gate-knn-risk-memory-brief.md`.
- Correlation-based exposure cap yang sesungguhnya (beda dari pengganti
  margin-ratio-cap di atas) — tidak ada metodologi di dokumen manapun;
  ditunda jadi item terpisah begitu ada histori multi-posisi nyata untuk
  didesain.
- Menyelesaikan diskrepansi 15% vs 20% `max_drawdown_pct` — dicatat untuk
  founder, bukan diputuskan di sini.
- Membangun orkestrator live (`custody/`, `graphs/`) yang dibutuhkan
  untuk benar-benar memberi gate ini state posisi nyata — pekerjaan
  terpisah yang sudah memblokir hal lain juga, bukan bagian brief ini.

## Referensi

`docs/prd.md` §3.1 Layer 3 (exposure caps), §6 Fase 4 (kill-switch
otomatis). `docs/kanban.md` — catatan "belum ada desain sama sekali"
yang memicu brief ini. `docs/margin-mode-brief.md` §7 — formula
margin-ratio-cap yang di-reuse. `docs/shadow-simulator-brief.md` §5 —
prinsip "kill-switch drawdown WAJIB hard-coded, tidak pernah ML" yang
jadi alasan tidak ada algoritma baru yang perlu didesain untuk 2 gate
pertama. `docs/regime-gate-knn-risk-memory-brief.md` — pola brief
docs-only yang diikuti dokumen ini.
