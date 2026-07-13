# Briefing Migrasi Compute: Railway -> VM Vultr (7 Juli 2026)

> **SUPERSEDED (13 Juli 2026)**: keputusan deploy mekanisme di bawah ini
> (docker-compose + Nginx + cron-polling auto-deploy manual) **diganti
> Coolify self-hosted** di VM Vultr yang sama -- Coolify sudah terinstal
> lebih dulu di VM ini (di luar sesi ini) dan lebih matang dari rencana
> cron-polling manual (native git-webhook auto-deploy, Traefik reverse
> proxy bawaan, API untuk provisioning/env var/log). Lihat
> `docs/deployment-runbook.md` (Gotcha Coolify) untuk cara kerja yang
> sekarang berlaku. Brief ini TETAP disimpan sbg catatan sejarah audit VM
> (topologi/kapasitas Markoviz, keputusan "VM yang sama, bukan VM baru")
> -- yang sudah tidak berlaku CUMA bagian mekanisme deploy (docker-compose/
> Nginx/cron-polling), bukan keputusan topologi VM-nya. Konteks "multi-
> produk sejak awal" di paragraf di bawah juga sudah tidak berlaku --
> scope Kinetiq dipangkas ke single-operator trading system 13 Juli 2026
> (`apps/platform-core/*` dihapus, lihat `CLAUDE.md`).

Keputusan hasil sesi grill-me (mengikuti `docs/ai-coding-workflow.md` Section
1.1) sebelum implementasi apa pun dimulai. Ini **sesi pertama** yang harus
dikerjakan sebelum slice lain di `docs/kanban.md` -- semua service baru
(platform-core, vertical trading gabungan Markoviz, dst) akan hidup di
infrastruktur ini, jadi keputusan di sini jadi fondasi buat kerja
berikutnya. Skalanya disesuaikan utk **multi-produk sejak awal** (bukan
cuma trading), krn ini yg jadi alasan migrasi ini terjadi sekarang (lihat
`docs/prd.md` A.6/B.6c/B.14c) -- **catatan historis, lihat banner di atas.**

## Keputusan yang sudah disepakati founder

1. **Topologi VM**: pakai **VM Vultr yang SAMA** dengan yang sudah live
   menjalankan Markoviz (`ai-perp-bot-core`) -- bukan VM baru terpisah.
   Implikasi: platform Kinetiq masuk ke VM yang sudah punya beban kerja
   produksi nyata (trading live). Ini menaikkan bobot langkah audit-dulu
   di bawah (harus pastikan kapasitas cukup & tidak ganggu Markoviz yang
   sudah jalan) dibanding kalau mulai dari VM kosong.
2. **Environment**: **satu VM production saja**, tidak ada VM staging
   terpisah. Testing pre-merge tetap lewat pola yang sudah jadi kebiasaan
   proyek ini: Neon `neon-preview-branch` (branch-per-PR ephemeral) utk DB,
   plus test lokal/CI utk kode. **Neon DB TIDAK ikut migrasi** -- cuma
   compute (yang sebelumnya Railway) yang pindah ke VM ini. Artinya
   concern lama soal "pengganti PITR/branching Neon di Postgres
   self-hosted" (pernah dicatat sbg TBD di revisi PRD sebelumnya) **sudah
   tidak relevan** -- Neon tetap dipakai apa adanya.
3. **Mekanisme deploy**: **cron-polling auto-deploy**, mengadopsi pola
   `ai-perp-bot-core/scripts/auto-deploy.sh` yang sudah terbukti live --
   VM cek repo secara berkala (mis. tiap beberapa menit) dan otomatis
   `git pull` + rebuild/restart container kalau ada commit baru di `main`.
   **Sengaja BUKAN GitHub Actions SSH-deploy-on-push** -- supaya siklus
   deploy Kinetiq tidak lagi bergantung sama sekali pada kuota Actions,
   yang baru saja jadi sumber masalah nyata (lihat
   `docs/deployment-runbook.md`). CI (lint/test) masih boleh tetap lewat
   GitHub Actions kalau kuota tersedia -- ini cuma soal jalur *deploy*,
   bukan jalur *testing*.
4. **Reverse proxy**: **Nginx** utk routing + HTTPS ke semua service yang
   hidup di VM ini (api-gateway, dashboard, endpoint per-vertical, dan
   proses Markoviz yang sudah ada).

## Yang masih perlu dikerjakan sbg slice pertama (bukan keputusan lagi, tapi kerja verifikasi)

Sebelum nulis docker-compose baru atau mindahin service apa pun, slice
pertama di `docs/kanban.md` **harus** berupa audit read-only ke VM yang
sudah live, karena keputusan #1 di atas (VM yang sama dengan Markoviz)
berarti kita menumpangi kapasitas yang sudah dipakai produksi nyata:

- SSH ke VM, cek resource yang tersedia (CPU/RAM/disk headroom di luar yang
  sudah dipakai Markoviz saat ini) -- kalau headroom tipis, itu jadi input
  keputusan (upgrade plan Vultr dulu vs mulai dgn subset service kecil).
- Cek docker-compose/layout yang sudah ada di VM itu skrg (nama container,
  port yang sudah dipakai, network Docker yang ada) -- supaya service baru
  Kinetiq tidak bentrok port/nama dgn container Markoviz yang sedang live.
- Cek proses non-Docker apa pun yang jalan di VM itu (cron job, systemd
  service) yang mungkin belum kecatat di `ai-perp-bot-core`'s dokumentasi
  sendiri (`VM-DEPLOY.md`).
- **Tidak boleh restart/stop apa pun di VM itu tanpa sepengetahuan founder
  scr eksplisit** -- Markoviz live, ada uang riil yang bisa kena dampak.

## Layout docker-compose yang diusulkan (draf, perlu direview founder)

Mengikuti struktur direktori agent-agnostic yang sudah ada di `docs/prd.md`
B.2 (`apps/platform-core/*` generik, `apps/products/<vertical>/*` per
produk), tiap servis jadi satu container:

```
docker-compose.yml (repo root, baru)
├── platform-core-api-gateway     # apps/platform-core/api-gateway
├── platform-core-dashboard       # apps/platform-core/dashboard-shell (Next.js)
├── platform-core-llm-gateway     # apps/platform-core/llm-gateway
├── platform-core-notification    # apps/platform-core/notification
├── trading-agent-orchestrator    # apps/products/trading/agent-orchestrator
├── trading-ingestion             # apps/products/trading/ingestion
├── trading-telegram-bot          # apps/products/trading/telegram-bot
├── nginx                          # reverse proxy, satu titik masuk utk semua di atas
└── (container Markoviz yang sudah ada -- TIDAK didefinisikan ulang di sini,
    tetap dikelola compose file `ai-perp-bot-core` sendiri sampai ada
    keputusan eksplisit lanjutan soal migrasi Markoviz masuk struktur ini)
```

Markoviz (`ai-perp-bot-core`) sengaja **tidak** langsung dipindah/ditulis
ulang ke compose file baru ini -- integrasinya ke mesin riset yang sama
sudah diputuskan di `docs/prd.md` B.6c, tapi itu perubahan *kode/logic*
(swarm digabung ke research engine), berbeda dari perubahan *infra*
(container mana yang hidup di VM mana) yang jadi topik brief ini. Kedua
proses container (compose lama Markoviz + compose baru Kinetiq) berjalan
berdampingan di VM yang sama dulu sampai integrasi kode selesai & diuji.

## Domain/subdomain (draf, perlu konfirmasi founder)

Custom domain `kinetiq.app` sebelumnya sengaja di-skip dulu (lihat
`docs/prd.md` catatan domain) demi fokus MVP. Migrasi ini jadi titik
alami utk aktifkan lagi kalau founder mau -- Nginx + Let's Encrypt
(certbot) butuh domain nyata utk HTTPS otomatis per-service (mis.
`api.kinetiq.app`, `app.kinetiq.app`). **Belum diputuskan** apakah
diaktifkan sekarang atau tetap pakai IP+port sementara di fase migrasi
awal -- item ini eksplisit belum final, jangan diasumsikan.

## Item yang sengaja TIDAK dibahas di sini (di luar scope brief ini)

- Migrasi kode/logic Markoviz ke `apps/products/trading/*` -- itu bagian
  dari B.6c, dikerjakan sbg slice kanban terpisah setelah infra ini siap.
- Rollback plan detail dari Railway kalau migrasi gagal -- akan dicatat
  begitu slice implementasi pertama (audit VM) selesai dan hasilnya
  diketahui (tidak bisa direncanakan presisi tanpa tahu kondisi VM dulu).
- Secrets management di VM (env file vs vault) -- proposal awal: `.env`
  per service dgn permission file ketat (`chmod 600`), pola paling
  sederhana yang cocok solo-founder; bisa direvisi begitu ada kebutuhan
  nyata utk sesuatu yg lebih kuat.

## Status

**Keputusan topologi/environment/deploy/reverse-proxy di atas sudah
final** (disepakati 7 Juli 2026). Detail layout compose & domain masih
draf yang perlu direview founder sebelum slice implementasi pertama
dibuka. Lihat `docs/kanban.md` utk slice konkret yang sudah dimasukkan
dari brief ini.
