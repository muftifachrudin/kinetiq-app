# Kanban — Tracer-Bullet Slices

Menu task yang dirujuk oleh `docs/ai-coding-workflow.md` Section 2.2/2.3.
**Satu slice = satu sesi Claude Code** — jangan campur dua card dalam satu
sesi, jangan bawa satu sesi lintas card. Pilih satu card, baca section
`docs/prd.md` yang direferensikan card itu untuk spec/keputusan sebenarnya
(board ini sengaja tidak mengulang isinya), ikuti checklist workflow,
lalu pindahkan ke Done dan tambahkan card lanjutan apa pun yang muncul
dari situ.

Card yang belum punya acceptance test yang jelas perlu sesi scoping/
"grill-me" dulu (workflow doc Section 1.1) sebelum sesi implementasi
dibuka untuk card tersebut.

## To Do

- [ ] **[SESI PERTAMA] Audit VM Vultr yang sudah live (Markoviz)** —
  langkah read-only sebelum service Kinetiq apa pun dipindah: cek
  resource headroom (CPU/RAM/disk), layout docker-compose/port/network
  yang sudah dipakai Markoviz, proses non-Docker yang jalan di VM itu.
  **Jangan restart/stop apa pun tanpa sepengetahuan founder eksplisit.**
  Hasil audit ini jadi input keputusan slice berikutnya (upgrade plan VM
  vs mulai subset service kecil). Refs: `docs/vultr-vm-migration-brief.md`.
- [ ] **Setup docker-compose + Nginx + cron-polling auto-deploy di VM
  Vultr** — setelah audit di atas selesai: tulis `docker-compose.yml`
  (layout draf sudah ada di brief, perlu direview founder dulu), config
  Nginx reverse proxy, dan cron job/systemd timer yang jalankan
  `auto-deploy.sh` (adaptasi pola `ai-perp-bot-core`). Refs:
  `docs/vultr-vm-migration-brief.md`.
- [ ] **Validasi perp/futures untuk pola Markoviz swarm** — pola
  `vibe-trading-ai` sudah tervalidasi untuk spot; jalankan walk-forward/
  PF-net-of-fees/bootstrap-CI dengan tingkat ketelitian yang sama seperti
  yang sudah dipakai untuk `fib_gann_timing`, sebelum pola ini dipercaya
  untuk perp/futures atau digabungkan ke shared research engine.
  Refs: `docs/prd.md` B.6c, `docs/fib-gann-validation-brief.md`.
- [ ] **Redesain Telegram signal card / trading status / analysis UI** —
  Telegram UI `ai-perp-bot-core` yang sekarang belum siap untuk bisnis;
  ini bukan sekadar port langsung, tapi benar-benar redesign. Refs:
  `docs/prd.md` B.6c, B.14.
- [ ] **RBAC per agent subscription (web app)** — guard di level route/
  middleware pada Next.js menggunakan `agent_subscription`, tanpa library
  RBAC baru. Refs: `docs/prd.md` B.14c, B.14b (tabel `agent_subscription`).
- [ ] **Halaman sidecar credential management — trading agent dulu** — satu
  form per tipe agent, dimulai dari API key CEX/DEX. Refs: `docs/prd.md`
  B.3b, B.14c.
- [ ] **Dashboard per agent — trading dulu** — bentuk dashboard bersifat
  spesifik per agent; jangan bangun dulu generic multi-agent dashboard
  shell (itu masih jadi diskusi terbuka, lihat bagian di bawah). Refs:
  `docs/prd.md` B.14c.
- [ ] **Halaman billing/subscription management** — route/state-nya
  dipisahkan secara arsitektur dari halaman config agent mana pun. Refs:
  `docs/prd.md` B.14c, `apps/platform-core/billing/` (B.2).

## Perlu didiskusikan dulu sebelum jadi slice

- **Bentuk dashboard gabungan untuk subscriber multi-agent** (tab switcher?
  satu halaman gabungan? widget yang bisa diatur user sendiri?) — sengaja
  belum diputuskan, jangan diimplementasikan sebelum didiskusikan. Refs:
  `docs/prd.md` B.14c.
- **"vibe-trading kasih analisis tiap 4 jam"** — masih ambigu, belum jelas:
  apakah ini pola cron yang sudah ada di `vibe-trading-ai`/swarm config,
  atau perilaku reporting baru dari research engine Kinetiq? Refs:
  `docs/prd.md` B.6c.
- **Domain/subdomain utk service di VM Vultr** — aktifkan `kinetiq.app`
  sekarang atau tetap IP+port sementara di awal migrasi? Belum
  diputuskan. Refs: `docs/vultr-vm-migration-brief.md`.
- **Migrasi kode/logic Markoviz masuk `apps/products/trading/*`** — beda
  dari migrasi infra (sudah diputuskan, lihat To Do di atas); ini soal
  kode/logic swarm digabung ke research engine, dikerjakan setelah infra
  VM siap. Refs: `docs/prd.md` B.6c.
- **Performa multi-timeframe research engine** — perlu sesi
  riset/implementasi khusus tersendiri. Refs: `docs/prd.md` B.6c.

## Done

(belum ada yang tercatat di sini sejak pengantar doc ini ditulis — semua
yang terjadi sebelum 7 Juli 2026 dilacak lewat task list milik sesi
masing-masing, bukan lewat board ini; mulai sekarang gunakan board ini.)
