# AI Coding Workflow — Konvensi Proyek Kinetiq

Diadaptasi dari talk Matt Pocock "Full Walkthrough: Workflow for AI Coding"
(AI Engineer 2026). Ini adalah **pull doc** yang dirujuk oleh `CLAUDE.md` —
detailnya ada di sini, bukan di `CLAUDE.md` itu sendiri, supaya context yang
selalu ter-load tetap tipis (lihat "Push vs Pull" di bawah). Baca dokumen ini
sebelum mulai fitur baru, dan baca ulang checklist di bagian bawah sebelum
setiap sesi.

## 0. Smart zone vs dumb zone

Setiap sesi punya "smart zone" (kira-kira ~100K token pertama) di mana model
mengikuti instruksi dan detail proyek dengan presisi. Setelah itu, sesi mulai
melenceng ke "dumb zone": makin sering halusinasi, keputusan-keputusan
sebelumnya terlupa, context lama dan baru bercampur aduk.

Implikasi praktis untuk repo ini:

- Jangan jalankan satu sesi Claude Code berjam-jam tanpa reset. Lebih baik
  pakai **`/clear` daripada `/compact`** saat berpindah topik (misalnya dari
  "validasi strategi" ke "shadow simulator" ke "migrasi infra Coolify")
  — auto-summary itu berisik dan bisa salah memprioritaskan. Ini yang
  disebut **"Memento Principle"**: simpan keputusan-keputusan penting ke
  dalam file yang persisten (`docs/prd.md`, sebuah brief, `CLAUDE.md`, sebuah
  issue) lalu mulai sesi baru yang bersih, alih-alih mengandalkan `/compact`
  untuk membawa semuanya terus.
- Mulai **sesi baru per topik**, bukan lanjutan dari sesi panjang.

## 1. Fase alignment — sebelum menulis kode apa pun

### 1.1 Grill-me first

Sebelum meminta agent mengimplementasikan sesuatu yang tidak trivial, biarkan
AI meng-interview *kamu* dulu — scope, edge case, constraint, definisi
"selesai" — daripada langsung loncat ke rencana. Jangan biarkan agent
lanjut ke tahap planning sebelum desainnya benar-benar jelas dan disepakati,
walaupun itu berarti butuh beberapa putaran tanya-jawab.

### 1.2 PRD sebagai penanda arah, bukan spec yang dikompilasi

`docs/prd.md` adalah **penanda arah (destination marker)** — arah dan
keputusan-keputusan kunci, bukan spec mekanis presisi yang dikompilasi
langsung oleh agent menjadi kode. Jangan terlalu dipoles: PRD yang terlalu
detail justru lebih cepat basi begitu implementasi mengungkap keputusan yang
lebih baik. PRD seharusnya menangkap masalah yang sedang diselesaikan,
constraint sistem, kriteria sukses, dan keputusan-keputusan kunci — bukan
setiap baris perilaku sistem. Terima bahwa PRD akan makin tidak sinkron
dengan implementasi seiring waktu; jangan kejar sinkronisasi 100%.

## 2. Fase planning — pemecahan task

### 2.1 Tracer bullets (vertical slices)

Pecah pekerjaan menjadi vertical slice yang memotong semua layer (DB → API →
UI/output) dalam skala kecil, alih-alih layer horizontal ("semua backend
dulu, baru semua frontend"). Setiap slice yang selesai menghasilkan sinyal
nyata yang bisa diuji end-to-end, dan slice-slice ini bisa dikerjakan secara
independen tanpa agent-agent saling bertabrakan.

Contoh untuk fitur trading-vertical: bukan "implementasikan semua 7 pillar
signal," tapi "pillar Aggressor Flow: raw orderbook data → score → publish
ke Redis → terlihat di log dashboard" — satu slice, tapi end-to-end dan bisa
diverifikasi secara independen.

### 2.2 Kanban dari slice-slice tersebut

Ubah slice-slice tadi menjadi papan Kanban (To Do → In Progress → Review →
Done). Ini menjadi "menu" tempat agent memilih task, dan menjadi dasar untuk
fase AFK di bawah. Papan proyek ini ada di `docs/kanban.md` — cek dulu
sebelum membuka sesi baru.

### 2.3 Satu sesi = satu slice (dikonfirmasi 7 Juli 2026)

Setiap kartu Kanban/slice tracer-bullet mendapat **sesinya sendiri yang
dedicated** — jangan gabungkan dua slice yang tidak berkaitan ke dalam satu
sesi panjang, dan jangan bawa sesi implementasi satu slice ke pekerjaan
slice berikutnya. Ini yang membuat "bisa diverifikasi secara independen" di
2.1 benar-benar terwujud dalam praktik: slice yang diimplementasikan dalam
sesinya sendiri bisa diuji end-to-end tanpa bergantung pada state slice lain
yang masih in-flight dan belum di-commit. Ini juga menjaga setiap sesi tetap
berada di dalam smart zone (Bagian 0), alih-alih menumpuk context yang tidak
saling berkaitan antar slice.

Rutinitas praktis untuk memulai sesi implementasi baru di repo ini:

1. Buka `docs/kanban.md`, pilih (atau tambahkan) slice yang akan dikerjakan.
2. Baca bagian `docs/prd.md` terkait yang dirujuk slice tersebut untuk
   keputusan/schema/constraint yang sebenarnya — entri kanban seharusnya
   merujuk ke sana, bukan menuliskannya ulang.
3. Ikuti checklist Bagian 6 di bawah untuk slice tersebut.
4. Pindahkan kartu ke Done di `docs/kanban.md` setelah di-merge, dan
   tambahkan slice-slice lanjutan baru yang terungkap darinya.

## 3. Fase eksekusi — human-in-the-loop dulu, baru otonom

### 3.1 TDD sebagai feedback loop agent

Kualitas feedback loop adalah **batas atas (ceiling)** dari kualitas output
agent. Tanpa cara objektif untuk tahu "apakah ini benar," agent akan berhenti
di titik "kelihatannya berhasil" — belum tentu "memang benar."

Alurnya: agent memilih task dari Kanban → menulis test dulu (sesuai
spec/acceptance criteria slice tersebut) → mengimplementasikan sampai test-nya
hijau → commit. Tetap human-in-the-loop selama fase ini, koreksi kesalahan
arah segera, dan **simpan setiap koreksi** ke dalam rule/skill/entri
`CLAUDE.md`, jangan hanya diulang secara verbal setiap sesi.

Untuk apa pun yang menyentuh path yang dilindungi CODEOWNERS
(`execution/risk_gate.py`, `execution/custody/*`, `packages/db/migrations/`)
atau logika yang kritikal terhadap strategi (scoring weight, gate
threshold), tetap human-in-the-loop — jangan promosikan ini ke AFK
sekalipun terasa makin rutin.

### 3.2 Mode AFK / otonom

Hanya setelah suatu pola terbukti konsisten benar untuk jenis task tertentu
(misalnya wiring rutin, boilerplate CRUD, mereplikasi pola yang sudah
tervalidasi ke exchange/venue baru) barulah task itu boleh dipindah ke
eksekusi otonom — menjalankan banyak slice tanpa supervisi real-time. Kurasi
Kanban dulu; jangan langsung loncat ke AFK untuk eksplorasi arsitektur baru.

## 4. Fase review — selalu di sesi yang bersih

Review kode hasil tulisan agent di **sesi baru yang bersih**, bukan sesi
yang sama dengan yang dipakai untuk implementasi — sesi implementasi penuh
dengan riwayat trial-and-error dan bukan titik pandang yang baik untuk
review yang objektif. Setelah automated review, tetap lakukan manual QA
sendiri — review oleh agent tidak menggantikan mencoba fitur itu secara
langsung, terutama untuk hal-hal yang soal "rasa" (UX, timing, tingkat
false-positive sinyal).

## 5. Desain codebase yang mudah dikerjakan agent

### 5.1 Standar push vs pull

- **Push** (selalu aktif, ada di `CLAUDE.md`): hal-hal yang harus selalu
  dipatuhi reviewer — style, constraint keamanan, batas arsitektur yang
  tidak boleh dilanggar.
- **Pull** (on-demand, ada di skill/dokumen terpisah): panduan yang hanya
  relevan saat implementer benar-benar membutuhkannya — misalnya cara
  memakai library tertentu, pola yang niche. Dokumen ini sendiri adalah
  pull doc.

Jangan taruh semuanya di `CLAUDE.md` — itu menghabiskan budget smart-zone
sejak awal setiap sesi. Simpan aturan yang wajib dan selalu berlaku di sana;
sisanya taruh di sini atau di skill khusus.

### 5.2 Software yang mudah "dibaca" agent (agent-legible)

Kode yang mudah di-refactor manusia juga mudah dikerjakan agent. Deep module
(interface sederhana, kompleksitas disembunyikan di dalam) tetap jadi target
yang tepat — agent tidak menggantikan kebutuhan akan fundamental software
yang baik, agent justru memberi reward pada codebase yang bersih dan
menghukum yang berantakan.

## 6. Checklist — sebelum memulai fitur baru

1. Mulai **sesi baru/bersih** — jangan lanjutkan sesi yang sudah panjang.
2. Jalankan sesi "grill-me": biarkan AI meng-interview kamu sampai desainnya
   jelas.
3. Tulis entri PRD singkat — masalah, constraint, kriteria sukses (jangan
   terlalu dipoles).
4. Pecah menjadi tracer bullet (vertical slice) → tambahkan ke Kanban.
5. Eksekusi human-in-the-loop dulu: agent memilih task → menulis test →
   mengimplementasikan → commit.
6. Simpan setiap koreksi ke dalam rule/skill/entri `CLAUDE.md`, bukan
   sekadar komentar sekali pakai.
7. Setelah polanya stabil, pindahkan task-task serupa ke mode
   otonom/AFK.
8. Review di sesi baru, lalu lakukan manual QA sendiri.
9. Jaga `CLAUDE.md` tetap tipis (hanya push rule); sisanya adalah pull
   doc/skill.

## Sumber

Video: Matt Pocock (@mattpocockuk), "Full Walkthrough: Workflow for AI
Coding," AI Engineer 2026. Dokumen ini diadaptasi dari rangkuman komunitas
atas talk tersebut (bukan transkrip verbatim), disesuaikan dengan stack repo
ini (Python/LangGraph + TypeScript + Redis + Postgres + Claude Code).
