# Deployment & Infra Runbook (Coolify + Neon + GitHub Actions)

Pengetahuan operasional dari proses membuat service pertama live -- awalnya
di Railway (`api-gateway`, sekarang dihapus), sekarang di Coolify self-hosted
(VM Vultr). Baca ini sebelum mengubah Dockerfile mana pun, config Coolify,
`.github/workflows/ci.yml`, atau apa pun di bawah `packages/db/migrations/`
-- setiap poin di bawah ini butuh satu deploy atau CI run yang gagal beneran
untuk ditemukan, dan mode kegagalannya cukup tidak jelas sehingga bisa
terulang lagi kalau tidak ditulis di sini.

Lihat `docs/prd.md` untuk PRD produk/arsitektur -- dokumen ini murni
mekanik deployment.

> **Status (13 Juli 2026): migrasi Railway -> Coolify SELESAI**, sekaligus
> dengan pemangkasan scope ke single-operator (`apps/platform-core/*`
> dihapus, lihat `CLAUDE.md`). Neon TETAP dipakai sbg DB -- semua gotcha
> Neon di bawah ini masih berlaku penuh. Gotcha Railway/Railpack di bawah
> ini sekarang **historis murni** (referensi kejadian nyata yang sudah
> terverifikasi selama Railway masih jadi compute aktif, Juli 2026) --
> `railway.toml`/`railway.ingestion-worker.toml` sudah dihapus dari repo,
> jangan diasumsikan masih relevan sbg target deploy aktif. Gotcha Coolify
> (di bawah, sebelum bagian Railway) adalah yang berlaku sekarang.
>
> **Gap terbuka yang sengaja belum diselesaikan**: dulu migrasi Alembic
> jalan otomatis tiap deploy lewat `api-gateway`'s Railway `startCommand`
> (`alembic upgrade head` sebelum `uvicorn` start). `api-gateway` sekarang
> dihapus, dan Dockerfile `apps/products/trading/ingestion` (satu-satunya
> service yang sudah live di Coolify saat ini) TIDAK menjalankan migrasi
> apa pun -- dia cuma background worker CEX polling, bukan tempat yang
> tepat utk memegang tanggung jawab DDL. Belum ada pengganti "siapa yang
> jalankan `alembic upgrade head` ke production tiap ada migration baru"
> di setup Coolify ini. Sampai ada keputusan (mis. service dedicated kecil,
> atau post-deployment command Coolify di salah satu app), migrasi ke
> production HARUS dijalankan manual lewat `scripts/manual-migrate-neon.sh`
> setelah tiap migration baru di-merge -- jangan asumsikan ada proses
> otomatis yang menjalankannya.

## Referensi topologi

- Repo: `kinetiq-app`, default branch `main`.
- Coolify self-hosted di VM Vultr yang sama yang menjalankan Markoviz
  (`ai-perp-bot-core`, live, TIDAK dikelola Coolify -- container Docker-nya
  sendiri, port internal-only, jangan pernah restart/stop tanpa
  sepengetahuan founder eksplisit). Project Coolify `kinetiq`, environment
  `production`, satu server (`localhost` -- itu Coolify host itu sendiri).
- Setiap service jadi satu Coolify **Application**, build pack
  `dockerfile`, Base Directory = repo root (`/`), Dockerfile Location =
  path Dockerfile relatif ke repo root (mis.
  `/apps/products/trading/ingestion/Dockerfile`) -- lihat gotcha Coolify
  #1 di bawah untuk kenapa ini wajib repo root, bukan subfolder.
- Branch default/primary di Neon project namanya **`production`**, bukan
  `main`. Nama branch git dan nama branch Neon itu dua skema penamaan yang
  independen -- jangan asumsikan keduanya sama.

## Gotcha Neon

0. **`neon-preview-branch` di CI belum pernah sekali pun menjalankan
   migration terhadap branch Neon `production` yang persisten dan
   sesungguhnya -- dan tidak ada proses lain juga yang menjalankan
   migration ke sana.** Ini menyebabkan downtime production sungguhan:
   request pertama yang benar-benar terautentikasi dan sampai ke query
   database di `api-gateway` (`GET /me` dengan Clerk session JWT asli,
   jauh setelah `FORCE ROW LEVEL SECURITY` dan alur auto-provision sudah
   di-deploy) crash dengan `psycopg.errors.UndefinedTable: relation
   "platform_user" does not exist`. Setiap deploy sebelumnya "berhasil"
   hanya karena setiap request yang diuji sejauh itu entah tidak punya
   auth token sama sekali (401 dilempar sebelum query DB apa pun), atau
   dijalankan lewat `dependency_overrides` yang di-mock di `TestClient`
   lokal, tidak pernah query sungguhan ke database sungguhan.
   `neon-preview-branch` hanya pernah membuat branch **baru, sementara,
   khusus per-PR**, menjalankan migration ke branch itu saja, lalu
   menghapusnya begitu PR ditutup -- ini tidak membuktikan apa-apa soal
   apakah `production` (atau branch Neon mana pun yang benar-benar
   ditunjuk oleh `DATABASE_URL` di Railway) pernah dijalankan `alembic
   upgrade head`. Lolos CI itu bukan klaim yang sama dengan "database
   sungguhan sudah di-migrate." **Perbaikan**: `startCommand` di
   `railway.toml` sekarang menjalankan `(cd packages/db && python -m
   alembic upgrade head)` sebelum menyalakan `uvicorn`, di setiap deploy
   (idempotent -- alembic melacak revision yang sudah diterapkan lewat
   tabel `alembic_version`, jadi no-op kalau sudah di head). `alembic`
   juga harus ditambahkan ke `requirements.txt` di root, karena
   `packages/db/pyproject.toml` (yang mencantumkannya sebagai dependency)
   tidak pernah di-pip-install oleh service ini, hanya direferensikan
   lewat `PYTHONPATH`. Service mana pun ke depannya yang punya migration
   sendiri butuh perlakuan "jalankan migration sebagai bagian dari
   startCommand" yang sama -- jangan asumsikan CI hijau berarti database
   target sudah benar-benar termigrasi.

1. **`DATABASE_URL` driver mismatch.** `create-branch-action` milik Neon
   (dan juga Railway) memberikan connection string `postgresql://...`
   polos. SQLAlchemy secara default mengarahkan scheme `postgresql://`
   polos ke dialect `psycopg2`, padahal project ini bergantung pada
   `psycopg` (v3), sehingga migration gagal dengan `ModuleNotFoundError:
   No module named 'psycopg2'` -- dan masalah persis yang sama juga
   muncul terpisah di `api-gateway/deps.py`, karena itu service lain
   dengan pemanggilan `create_engine()` sendiri. Sudah diperbaiki sekali,
   dipakai bersama di mana-mana: `kinetiq_db.engine.normalize_db_url()`
   memaksa driver `postgresql+psycopg` lewat `make_url(...).set(drivername=...)`
   apa pun scheme yang masuk -- setiap service yang membuka koneksi DB
   sebaiknya memanggil fungsi ini, bukan langsung
   `create_engine(os.environ["DATABASE_URL"])`.
   Gotcha di dalam gotcha: pakai `.render_as_string(hide_password=False)`,
   bukan `str(url)` -- yang terakhir ini menyamarkan password jadi `***`
   dan diam-diam merusak proses autentikasi.

2. **CI *bisa* menjangkau Neon sungguhan meski sesi interaktif ini tidak
   bisa.** Kebijakan jaringan sesi Claude Code yang di-sandbox memblokir
   `console.neon.tech`, tapi itu tidak berpengaruh sama sekali ke GitHub
   Actions runner, yang punya akses internet normal. Jangan asumsikan
   sebuah migration "tidak bisa diuji ke Neon sungguhan" hanya karena
   sesi interaktif tidak bisa menjangkaunya langsung -- buka PR dan
   biarkan `neon-preview-branch` di CI yang melakukannya.

3. **`base_branch` di `schema-diff-action` harus diisi nama branch Neon**
   (`production`), bukan nama branch git (`main`). Ini dikonfirmasi
   lewat kegagalan `##[error]Branch main not found in project`.

4. **`SET x = :param` tidak menerima bind parameter -- Postgres akan
   menolaknya dengan syntax error di level protokol** (`SET
   app.tenant_id = $1` -> `syntax error at or near "$1"`), karena `SET`
   adalah utility statement, bukan DML biasa yang bisa memakai
   substitusi parameter dari extended query protocol. Ini sempat
   tersembunyi tanpa disadari di `api-gateway/deps.py` (`SET
   app.tenant_id = :tenant_id`) sejak PR middleware tenant auth --
   tidak pernah benar-benar error, karena belum ada login sungguhan
   dengan `tenant_id` non-null yang lewat situ (setiap request
   sungguhan sejauh itu entah tanpa token sama sekali, atau belum
   punya tenant). Masalah ini muncul begitu policy RLS mulai benar-benar
   diquery dalam test dengan session tenant sungguhan. Perbaikan: pakai
   `SELECT set_config('app.tenant_id', :tenant_id, false)` -- karena
   `set_config()` adalah pemanggilan fungsi biasa, jadi substitusi bind
   parameter normal berfungsi. Kode apa pun ke depannya yang men-set
   GUC session Postgres dari variabel Python wajib pakai `set_config()`,
   jangan `SET` yang di-string-format atau diparameterkan.

5. **GUC custom (bernamespace `app.*`) yang belum pernah di-`SET` dalam
   session yang sedang berjalan bisa terbaca kembali sebagai `''` (string
   kosong) lewat `current_setting(name, true)`, bukan `NULL`** -- begitu
   ada session mana pun di server yang pernah memakai nama GUC itu,
   Postgres mendaftarkannya sebagai placeholder variable yang dikenal,
   dan instance yang belum di-set di session baru jadi default ke `''`,
   bukan benar-benar hilang/`NULL`. Ini merusak ekspresi policy RLS
   `tenant_id = current_setting('app.tenant_id', true)::uuid` dengan
   error `invalid input syntax for type uuid: ""` pertama kali sebuah
   session mengenainya tanpa pernah memanggil
   `set_config('app.tenant_id', ...)` sendiri (misalnya session
   superadmin, yang memang tidak pernah men-set `app.tenant_id` sama
   sekali). Perbaikan: `NULLIF(current_setting(name, true), '')::uuid`
   -- ini menyatukan kasus belum-pernah-di-set-di-mana-pun (`NULL`) dan
   di-set-di-tempat-lain-tapi-tidak-di-sini (`''`) jadi `NULL` sebelum
   di-cast, alih-alih membiarkan keduanya langsung masuk ke cast.

## Gotcha Coolify

Ditemukan lewat deploy sungguhan pertama ke Coolify (13 Juli 2026,
`kinetiq-ingestion-worker`), bukan dari baca dokumentasi Coolify saja --
2 dari 3 gotcha di bawah baru ketauan setelah container jalan tapi salah.

1. **Base Directory HARUS repo root (`/`), bukan folder service** --
   padanan Docker dari masalah "Root Directory" Railway (gotcha Railway #7
   di bawah), versi Docker-nya: `COPY` di Dockerfile tidak pernah bisa
   menjangkau apa pun di luar build context, dan build context Coolify =
   Base Directory. Service mana pun yang butuh sibling package
   (`packages/db`, atau modul lain di monorepo) WAJIB Base Directory = repo
   root + Dockerfile Location berupa path relatif ke repo root (lihat
   `apps/products/trading/ingestion/Dockerfile`, yang `COPY packages/db`
   DAN `COPY apps/products/trading/agent-orchestrator` sebagai sibling
   eksplisit -- yang kedua ketauan cuma dari deploy gagal beneran dengan
   `ModuleNotFoundError: fib_gann_timing`, bukan dari baca kode
   `signal_loop.py` saja, karena sys.path-nya relatif dan tidak jelas
   sekilas modul mana yang benar-benar perlu di-`COPY`).

2. **Field `git_repository` di API `/applications/public` butuh URL penuh**
   (`https://github.com/<owner>/<repo>`), BUKAN bentuk pendek
   `<owner>/<repo>` -- meskipun beberapa app lain yang sudah ada di
   instance Coolify yang sama menyimpan bentuk pendek itu (app yang
   terhubung lewat GitHub App/Source terdaftar, jalur API yang berbeda).
   Validasi API menolak eksplisit dengan pesan "must start with https://,
   http://, git://, or git@" kalau salah format.

3. **`PYTHONUNBUFFERED=1` wajib di-set untuk service Python apa pun yang
   logging-nya lewat `print()`/stdout biasa.** Tanpa ini, Python
   full-buffer stdout begitu bukan TTY (selalu begitu di Docker) --
   container Coolify berjalan sehat (build sukses, status `running`),
   tapi log-nya kosong total sampai buffer penuh atau proses exit. Ini
   BUKAN masalah Coolify -- ini perilaku default Python di container mana
   pun -- tapi baru kelihatan dampaknya begitu benar-benar deploy proses
   long-running yang loggingnya berkala (kebalikan dari script pendek yang
   exit cepat, di mana buffer keburu di-flush saat proses selesai).

4. **Trigger deploy lewat API**: `GET /api/v1/deploy?uuid=<application_uuid>`
   (bukan POST) mengembalikan `deployment_uuid`, poll statusnya via
   `GET /api/v1/deployments/{deployment_uuid}` sampai `status` jadi
   `finished`/`failed`. Env var di-set lewat
   `POST /api/v1/applications/{uuid}/envs` (`is_literal: true` supaya
   karakter spesial di value seperti `!`/`&` tidak diinterpretasi ulang;
   `is_shown_once: true` supaya value tidak balik ditampilkan plaintext di
   UI setelah di-set).

5. **Dua endpoint log yang bentuknya beda, jangan tertukar** (padanan
   "Build Logs vs Deploy Logs" Railway di bawah, tapi shape response-nya
   beda total): `GET /api/v1/applications/{uuid}/logs` mengembalikan satu
   string log container (tail runtime stdout/stderr) di field `logs`.
   `GET /api/v1/deployments/applications/{uuid}` mengembalikan daftar
   deployment, masing-masing dengan field `logs`-nya SENDIRI berupa STRING
   berisi JSON-encoded array `{output, type, timestamp}` (bukan array
   langsung -- perlu `json.loads()` dua kali berturut-turut: sekali untuk
   response HTTP-nya, sekali lagi untuk field `logs` di dalamnya). Yang
   pertama untuk "apakah proses ini sehat sekarang", yang kedua untuk
   "kenapa build/deploy terakhir gagal". `tools/coolify_logs.py`
   membungkus keduanya (`--logs container` / `--logs build`).

## Gotcha Railway / Railpack (historis -- Railway sudah tidak dipakai)

1. **`railway.toml` harus ada di repo root**, tidak boleh di dalam Root
   Directory sebuah service. Resolusi file config-as-code Railway tidak
   mengikuti setting Root Directory -- selalu diresolve dari repo root.
   Command *di dalam* file itu (`buildCommand`, `startCommand`) tetap
   dieksekusi relatif terhadap Root Directory yang dikonfigurasi di
   dashboard, jadi tulis path di dalam file itu seolah `cwd` sudah ada
   di direktori service.

2. **Menambahkan service Railway ke-2 dan seterusnya**: setiap service
   baru butuh Root Directory sendiri di dashboard (Settings -> Source),
   dan kalau butuh `railway.toml` sendiri, butuh path Config-as-code
   eksplisit per service (Settings -> Config-as-code) -- ini hanya bisa
   dilakukan dari dashboard/GraphQL API, tidak bisa dari dalam file config.

3. **Jangan override `[build] buildCommand` untuk service Python kecuali
   memang ada alasan spesifik.** Dua mode kegagalan sudah dialami di sini,
   berurutan:
   - Dengan `buildCommand = "pip install -e ."` pada project
     `pyproject.toml`: build log menunjukkan `pip install` sukses
     (`Successfully installed ... uvicorn-0.49.0`), tapi image runtime
     tetap tidak punya package itu (`No module named uvicorn`). Command
     custom ini melewati mekanisme native install step milik Railpack
     yang seharusnya mempersist package terinstal dari build stage ke
     image runtime final.
   - Tanpa `buildCommand` sama sekali: deteksi Python zero-config milik
     Railpack mengenali bahwa project `pyproject.toml`/setuptools ada,
     tapi tidak meng-auto-generate install step sama sekali untuknya
     (tidak ada lockfile Poetry/uv yang dikenali secara native) -- build
     log langsung lompat dari "Detected Python" ke "Deploy" tanpa install
     step di antaranya, jadi tidak ada apa pun yang terinstal.
   - **Yang benar-benar berhasil**: `main.py` flat + `requirements.txt`
     polos (tanpa layout package `src/`, tanpa `pyproject.toml`). Railpack
     punya dukungan native yang solid untuk `requirements.txt` dan benar
     mempersist hasil install ke image runtime. `main.py` di root service
     langsung bisa diimport (`python -m uvicorn main:app`) tanpa install
     step sendiri -- hanya dependency pihak ketiga yang butuh
     `requirements.txt`.
   - Kalau ke depannya ada service yang benar-benar butuh Poetry/uv/
     package yang benar-benar installable, verifikasi dukungan native
     Railpack untuk tool spesifik itu *dulu*, jangan langsung pakai
     override `buildCommand` custom.

4. **Pakai `python -m uvicorn ...`, jangan binary `uvicorn` polos, di
   `startCommand`.** Railpack mengelola Python lewat `mise`; shim
   console-script untuk `uvicorn` tidak selalu ada di `PATH` yang
   diwariskan `bash -c` di deploy stage (`uvicorn: command not found`
   pada praktiknya), tapi `python` itu sendiri selalu bisa diresolve.
   Logika yang sama berlaku untuk entry point console-script lain
   (`gunicorn`, `alembic`, dll) kalau suatu saat perlu dijalankan sebagai
   start/build command Railway.

5. **Build Logs dan Deploy Logs menunjukkan kelas kegagalan yang
   berbeda -- minta keduanya saat debug kegagalan Railway.** Build Logs
   menunjukkan apakah dependency berhasil terinstal. Deploy Logs
   menunjukkan stdout/stderr container sungguhan (traceback crash, baris
   startup `INFO: Uvicorn running on ...` yang asli, dan percobaan retry
   healthcheck). Banner "Healthcheck failed" saja tidak cukup informasi --
   tampilannya identik entah aplikasinya crash instan atau memang ada
   masalah networking/port yang salah konfigurasi. Ambil Deploy Logs
   dulu sebelum berteori.

6. **"Unexposed service" / ambiguitas port adalah jalan buntu yang
   kelihatannya masuk akal.** Ada mode kegagalan Railway yang nyata dan
   terdokumentasi di mana healthcheck sebuah unexposed service gagal
   karena Railway tidak bisa menentukan port mana yang harus dicek, bisa
   diperbaiki dengan men-set variabel `PORT` eksplisit. Ini sudah dicoba
   di sini dan *tidak* memperbaiki masalah sebenarnya, karena penyebab
   aslinya (bug #3/#4 di atas) adalah proses yang memang tidak pernah
   berhasil start sama sekali. Jangan berhenti menyelidiki hanya karena
   ada fix komunitas Railway yang kelihatannya masuk akal untuk gejala
   yang mirip-mirip -- konfirmasi dulu lewat Deploy Logs.

7. **Sibling package di monorepo (mis. `packages/db`, direferensikan
   dari service yang Root Directory-nya adalah subfolder seperti
   `apps/platform-core/api-gateway`) tidak pernah bisa dijangkau, dengan
   cara apa pun -- bukan lewat `-e ../../../packages/db` di
   `requirements.txt` (gagal dengan `ERROR: ../../../packages/db is not
   a valid editable requirement`), dan bukan juga lewat
   `PYTHONPATH=../../../packages/db/src` di `startCommand` (ter-deploy
   dengan mulus, lalu crash saat runtime dengan `ModuleNotFoundError: No
   module named 'kinetiq_db'`).** Root cause-nya, dikonfirmasi dengan
   mereproduksi traceback yang persis sama secara lokal dengan *hanya*
   folder service itu sendiri yang ada di disk (tanpa sibling monorepo
   lain): setting "Root Directory" di Railway membatasi **seluruh**
   konteks build *dan* runtime ke satu subfolder itu saja -- direktori
   sibling tidak pernah ikut ter-copy, di stage build mana pun atau saat
   runtime. (Teori awal di sini -- bahwa ini cuma masalah timing Docker
   layer-caching, yang bisa diperbaiki dengan menunda referensi sibling
   dari pip-install saat build-time ke `PYTHONPATH` saat runtime-time --
   ternyata salah. Ini bukan soal timing, direktori sibling itu memang
   secara kategoris tidak ada di container tersebut, selamanya.) Ini
   sesuai dengan cara kerja scoping "root directory"/"working directory"
   di kebanyakan platform PaaS secara umum, bukan quirk khusus Railpack.
   **Perbaikan**: ubah Root Directory service itu di Railway dashboard
   (Settings -> Source) ke **repo root** (kosong), bukan subfolder
   service. Pindahkan `requirements.txt` service itu ke **repo root**
   juga, supaya deteksi Python zero-config milik Railpack tetap memicu
   secara native (tidak perlu `[build] buildCommand` custom -- lihat
   gotcha #3 di atas untuk alasan kenapa itu sebaiknya dihindari).
   Lalu di `startCommand`, set `PYTHONPATH` untuk mencakup *baik*
   direktori source package sibling *maupun* folder service itu sendiri
   (relatif terhadap repo root sekarang, mis.
   `PYTHONPATH=packages/db/src:apps/platform-core/api-gateway python -m
   uvicorn main:app ...`) -- folder service itu perlu eksplisit ada di
   `PYTHONPATH` sekarang juga, karena `main.py` tidak lagi otomatis ada
   di `sys.path`/cwd begitu Root Directory adalah repo root. Verifikasi
   ini dengan mereproduksi layout file container yang sebenarnya secara
   lokal (copy *hanya* folder service ke temp dir kosong dan jalankan
   dari situ) sebelum mempercayai teori "seharusnya berhasil" apa pun
   soal build context Railway -- itulah yang menangkap fix pertama yang
   salah untuk bug ini.
   Service mana pun ke depannya yang perlu memakai ulang `packages/db`
   (atau shared package lainnya) sebaiknya pakai pola
   Root-Directory-di-repo-root + `PYTHONPATH` gabungan ini, bukan
   editable pip install dan bukan `PYTHONPATH` yang relatif terhadap
   subfolder. Hanya bisa ada satu `railway.toml` dan satu
   `requirements.txt` root di repo root, jadi service Python kedua yang
   punya kebutuhan sama akan butuh solusi berbeda (mis. Railpack config
   khusus atau skema marker file repo-root sendiri) -- jangan asal
   copy-paste pola ini untuk service #2.

8. **"Solusi berbeda" yang diflag gotcha #7 untuk service Python ke-2
   ternyata: gabungkan dependency-nya ke `requirements.txt` root yang
   SAMA, jangan bikin file baru.** Konkretnya ditemui saat menambahkan
   `apps/products/trading/ingestion/worker.py` sebagai service Railway
   sendiri (3 Juli 2026): dia juga butuh `packages/db`, jadi sesuai
   gotcha #7 Root Directory-nya *juga* harus repo root -- tapi deteksi
   Python zero-config milik Railpack hanya pernah membaca SATU
   `requirements.txt`, di repo root, per service yang
   Root-Directory-nya-di-repo-root. Dua service yang sama-sama berakar
   di repo root tidak bisa masing-masing membawa file requirements
   dengan nama berbeda tanpa `[build] buildCommand` custom (yang
   membuka kembali kelas kegagalan gotcha #3 "terinstal di build log,
   tidak pernah sampai ke image runtime" -- tidak sepadan risikonya untuk
   hal yang sebenarnya bisa dihindari). **Perbaikan**: menambahkan
   dependency ekstra `worker.py` yang benar-benar dipakai (`ccxt`,
   `requests` -- `sqlalchemy`/`psycopg[binary]` sudah ada duluan untuk
   api-gateway) langsung ke `requirements.txt` root yang sudah ada,
   supaya kedua service sama-sama install dari satu file yang sudah
   dideteksi Railpack secara native. `railway.<name>.toml` milik service
   itu sendiri (mis. `railway.ingestion-worker.toml`) tetap butuh path
   Config-as-code eksplisit yang di-set di Settings dashboard service itu
   (Railway hanya auto-discover file yang namanya literally
   `railway.toml`) -- bagian gotcha #2 itu tetap berlaku, hanya bagian
   file requirements yang butuh jawaban berbeda dari "kasih file
   sendiri."
   **Berlaku juga untuk service tipe worker (non-web)**: tidak ada
   `PORT`/`healthcheckPath` yang relevan karena tidak ada HTTP server
   yang diprobe -- Railway mengawasi prosesnya sendiri; pilih
   "worker"/"background" sebagai tipe service di dashboard kalau
   ditanya, dan set `restartPolicyType = "always"` supaya kalau crash
   akan di-retry, bukan dibiarkan mati.
   **TERVERIFIKASI ke platform sungguhan (3 Juli 2026, percobaan deploy
   pertama founder)** -- berhasil dengan benar di percobaan pertama,
   tanpa perlu perbaikan apa pun: service `ingestion-worker` (Root
   Directory = repo root, Config-as-code = `railway.ingestion-worker.toml`)
   berhasil dibangun dan di-deploy, Deploy Logs menunjukkan urutan yang
   diharapkan secara lengkap (`backfill starting: 365 days back` -> 4x
   `backfill OK (8760 candles ...)` untuk binance+bybit x BTC/ETH ->
   `backfill done -- entering live poll loop` -> satu siklus poll
   funding_rate+ohlcv per instrument, semuanya `(ccxt)` -> `sleeping
   2718s until next 1h close`). Ini juga verifikasi real-network pertama
   untuk Bybit di seluruh sejarah repo ini (sebelumnya cuma di-mock,
   lihat `apps/products/trading/ingestion/README.md`) -- berhasil tanpa
   perlu fix apa pun. Ini mengonfirmasi pola merged-root-requirements.txt
   + toml-bernama-terpisah + path-Config-as-code-eksplisit yang
   dijelaskan gotcha ini memang solid, bukan sekadar teori di atas kertas.

## Status & log Railway lewat GraphQL (historis -- diganti `tools/coolify_logs.py`, lihat Gotcha Coolify #5 di atas)

Dulu setiap langkah "ambil KEDUA Build Logs dan Deploy Logs" di atas
berarti founder harus buka dashboard Railway dan screenshot. Sekarang
keduanya cukup satu command saja dari environment mana pun yang punya
`RAILWAY_TOKEN` ter-set (terverifikasi ke project sungguhan, 2026-07-04):

```
python tools/railway_logs.py                              # latest deployment per service
python tools/railway_logs.py --service api-gateway --logs both
python tools/railway_logs.py --deployment-id <uuid> --logs deploy --limit 300
```

Fakta API yang dipelajari lewat trial-and-error (sudah tertanam di
script, diulang di sini supaya tidak ada yang menemukannya ulang
dengan cara susah):

- Endpoint: `POST https://backboard.railway.com/graphql/v2`. Untuk
  **Project Token**, header auth-nya adalah **`Project-Access-Token:
  <token>`** -- `Authorization: Bearer` itu untuk personal/team token
  dan TIDAK berfungsi dengan project token.
- **Cloudflare menolak User-Agent default Python's urllib** dengan
  HTTP 403 body `error code: 1010`. Header `User-Agent` eksplisit apa
  pun lolos. Ini bukan kegagalan auth -- jangan rotate token gara-gara
  ini (curl langsung berfungsi out of the box karena default UA-nya
  lolos).
- Project Token itu di-scope ke satu project+environment dan **tidak
  bisa membaca `project(id: ...)`** (403 polos). Yang BISA dibaca sudah
  cukup: `projectToken` (mengembalikan projectId/environmentId-nya
  sendiri -- tidak perlu hardcode), `deployments(input: {projectId,
  environmentId})`, `buildLogs(deploymentId, limit)`,
  `deploymentLogs(deploymentId, limit)`. Nama service ditemukan lewat
  daftar deployments.
- **Severity di `deploymentLogs` mencerminkan stream-nya, bukan
  maknanya**: apa pun yang ditulis container ke stderr kembali sebagai
  `severity: "error"` -- uvicorn dan alembic menulis baris INFO normal
  mereka ke stderr, jadi deretan baris INFO dengan severity=error itu
  adalah deploy yang SEHAT. Baca teks pesannya. Build logs menyisipkan
  kode warna ANSI (script secara default menghapusnya; `--raw`
  mempertahankannya).

## Gotcha Row-Level Security (RLS) (historis -- RLS dihapus total 13 Juli 2026, migration `0009_drop_platform_core_and_tenancy.py`)

Kinetiq sekarang single-operator (tidak ada konsep tenant sama sekali) --
RLS, `tenant_isolation` policy, dan `tenant_id` sudah dihapus dari semua
tabel trading. Bagian ini dipertahankan sbg catatan sejarah kenapa
desainnya dulu seperti ini (dan sbg referensi kalau suatu saat konsep
multi-user perlu dihidupkan lagi), bukan panduan operasional yang masih
berlaku hari ini.

1. **`FORCE ROW LEVEL SECURITY` wajib, bukan opsional, dengan setup
   koneksi hari ini.** Postgres mengecualikan *owner* sebuah tabel dari
   RLS sepenuhnya kecuali `FORCE` juga di-set. `DATABASE_URL` aplikasi
   saat ini konek sebagai role yang sama dengan yang memiliki (owner)
   setiap tabel (belum ada role app dengan least-privilege terpisah) --
   tanpa `FORCE`, setiap policy yang ditambahkan di sini akan jadi
   no-op total terhadap query aplikasi sendiri, sambil tetap kelihatan
   "aktif" di `\d <table>`. `FORCE` hanya memengaruhi DML
   (SELECT/INSERT/UPDATE/DELETE); migration itu DDL dan tidak
   terpengaruh olehnya.

2. **`platform_user` sengaja tidak punya policy RLS**, meskipun punya
   kolom `tenant_id`. `get_current_user()` di `api-gateway/deps.py`
   mencari caller lewat `clerk_user_id` *sebelum* `tenant_id` diketahui
   -- lookup itu sendiri adalah cara tenant-nya ditemukan pertama kali.
   Policy tenant-scoped di `platform_user` akan membuat lookup diri
   sendiri saat login jadi tidak terlihat oleh dirinya sendiri (RLS
   menolak secara default kalau session var belum di-set), sehingga
   merusak auth untuk setiap user di setiap request. Kalau suatu saat
   memang ada kebutuhan nyata membatasi visibilitas `platform_user`,
   itu bukan pola `tenant_id = ...` yang sesederhana ini.

3. **`llm_config` butuh bentuk policy yang berbeda dari tabel tenant
   lainnya**: `tenant_id IS NULL OR tenant_id = current_setting(...)`,
   bukan strict match. Baris `tenant_id` yang `NULL` di situ adalah
   config `scope='global'`/`'product'` yang dishare (hierarki resolusi
   tenant->product->global di Section B.13), bukan "data milik tidak
   ada siapa-siapa" -- policy strict akan membuat setiap session tenant
   buta terhadap default global/product yang seharusnya jadi fallback-nya.

4. **Insert manual lewat `psql`/admin ke tabel yang diproteksi RLS
   butuh `SELECT set_config('app.is_superadmin', 'true', false);`
   dijalankan dulu di session yang sama**, atau akan ditolak oleh
   klausa `WITH CHECK` policy tersebut (mis. saat bootstrapping
   baris superadmin/tenant paling pertama, sebelum ada kode aplikasi
   yang jalan untuk men-set session context). Ini bukan workaround --
   ini memang escape hatch admin yang disengaja, mekanisme yang sama
   yang dipakai aplikasi sendiri.

5. **Bagaimana ini sebenarnya diverifikasi secara lokal** (layak dipakai
   ulang untuk pekerjaan policy RLS mana pun ke depannya, karena testing
   sebagai role superuser `postgres` tidak membuktikan apa-apa --
   superuser Postgres bypass RLS tanpa syarat, titik, terlepas dari
   `FORCE`): buat role non-superuser khusus, alihkan ownership tabel ke
   role itu (`ALTER TABLE ... OWNER TO ...`), konek sebagai role itu,
   dan konfirmasi (a) koneksi baru tanpa session var apa pun yang
   di-set melihat nol baris (fail closed), (b) session tenant-scoped
   hanya melihat baris miliknya sendiri, (c) `INSERT` lintas tenant
   ditolak, dan (d) `app.is_superadmin = 'true'` melihat semuanya.
   Urutan persis ini yang menangkap gotcha #4 dan #5 di bagian gotcha
   Neon di atas -- keduanya baru muncul begitu kita menjalankan session
   *kedua* yang belum pernah dipakai sebelumnya (mis. session superadmin
   baru yang tidak pernah memanggil `set_config` sendiri).

## `order_audit_log` append-only (`packages/db/migrations/versions/0003_order_audit_log_append_only.py`)

**`REVOKE UPDATE, DELETE ON order_audit_log FROM <role>` akan jadi
no-op diam-diam**, dengan alasan persis sama kenapa `FORCE ROW LEVEL
SECURITY` wajib di migration 0002: object owner di Postgres selalu
mempertahankan hak penuh atas object yang mereka miliki, terlepas dari
`GRANT`/`REVOKE` apa pun -- dan tidak seperti RLS, tidak ada padanan
`FORCE` untuk privilege yang bisa meng-override itu. Role
`DATABASE_URL` aplikasi adalah owner dari `order_audit_log`, jadi
`REVOKE` polos akan kelihatan seperti melakukan sesuatu padahal tidak
mengubah apa-apa.

**Perbaikan yang dipakai sebagai gantinya: trigger `BEFORE UPDATE OR
DELETE` yang unconditionally melempar exception.** Trigger tetap
jalan terlepas dari role atau ownership -- tidak ada pengecualian
owner, tidak ada bypass `is_superadmin`, tidak ada apa-apa. Sudah
diverifikasi secara lokal dengan konek sebagai superuser `postgres`
(owner tabel itu) dan mengonfirmasi baik `UPDATE` maupun `DELETE`
ditolak dengan pesan `order_audit_log is append-only: <OP> is not
allowed`, sementara `INSERT` normal tetap berhasil. Ini memang
disengaja, bukan celah yang perlu diperbaiki nanti: audit trail yang
bisa diedit lewat jalur aplikasi normal oleh role mana pun (termasuk
yang paling dipercaya sekalipun) sebenarnya bukan audit trail. Kalau
suatu saat memang butuh koreksi sungguhan, itu jadi baris kompensasi
baru, bukan edit ke histori -- dan kalau memang ada kebutuhan darurat
perbaikan schema, itu harus lewat
`ALTER TABLE order_audit_log DISABLE TRIGGER order_audit_log_append_only`
yang disengaja dan diaudit terpisah oleh DBA, bukan sesuatu yang bisa
di-opt-out diam-diam lewat session variable mana pun.

Kalau ke depannya ada tabel lain yang butuh jaminan "insert-only, tidak
boleh diedit/dihapus sama sekali" yang sama, langsung pakai pola trigger
ini -- jangan coba `REVOKE` dulu dan menemukan ulang hal ini dengan cara
susah.

## Workaround push-to-`main` GitHub (situasional, bukan berlaku selamanya)

Sebelumnya di project ini, git relay sesi ini mengembalikan 503 yang
persisten pada push langsung ke `main` (kelihatannya di-scope ke nama
branch *asli* sesi ini, sebelum di-rename jadi `main` di GitHub).
Workaround-nya: push ke nama branch lama (yang masih diterima relay),
lalu buka PR dari branch itu ke `main` dan merge lewat GitHub API. Kalau
suatu sesi ke depannya mengalami `git push origin <local>:main` gagal
dengan 503 sementara `git ls-remote` (read-only) berfungsi normal, ini
pola yang harus dipakai -- ini quirk sesi/relay, bukan masalah
permission yang sesungguhnya.

## Script manual deploy/migrate (jatah menit GitHub Actions habis, 5 Juli 2026)

`scripts/manual-deploy-coolify.sh <application-uuid>` dan `scripts/manual-
migrate-neon.sh` -- untuk dipakai dari mesin lokal mana pun (MobaXterm di
Windows, Termux di Android, atau shell laptop biasa) saat GitHub
Actions tidak tersedia (mis. jatah menit Actions bulanan akun sudah
habis -- terlihat di Settings -> Billing -> "Metered usage"). Keduanya
adalah wrapper tipis di sekitar Coolify API / Alembic, sudah
didokumentasikan dengan langkah setup satu kali di comment header
masing-masing -- baca itu dulu sebelum pemakaian pertama, tidak
direproduksi di sini supaya kedua salinan tidak saling melenceng.
(`scripts/manual-deploy-railway.sh` yang lama sudah dihapus bersamaan
dengan migrasi ke Coolify.)

Penting: deploy Coolify sendiri itu **integrasi GitHub native** (git
source per-application, webhook Coolify), bukan workflow GitHub Actions --
ini sudah auto-deploy di setiap push ke branch yang dikonfigurasi terlepas
dari kuota/status Actions. Script ini ada untuk deploy *tanpa* harus push
ke git dulu, atau sebagai trigger manual kalau webhook-nya sendiri suatu
saat macet -- bukan karena merge normal diblokir oleh kuota Actions.
Lihat juga catatan "gap terbuka" di atas soal migrasi -- `manual-migrate-
neon.sh` bukan cuma fallback saat Actions habis kuota, itu SATU-SATUNYA
jalur migrasi ke production saat ini.

Kalau jatah menit GitHub Actions habis untuk sisa siklus billing dan
self-hosted runner belum di-setup, merge PR tetap bisa lanjut tanpa
green check CI lewat manual review + `pytest`/`ruff check` lokal (cek
yang sama yang akan dijalankan CI) -- ini pengecualian yang
terdokumentasi dan disengaja untuk situasi spesifik itu, bukan lisensi
umum untuk skip CI.

## Checklist verifikasi sebelum push perubahan infra/config

- **Build Dockerfile-nya persis (`docker build` dari repo root, base
  directory yang sama seperti build context Coolify), jangan cuma
  jalankan aplikasi secara lokal dengan cara gampang.** Kalau `docker`
  tidak tersedia di environment kerja (mis. sandbox bersarang), minimal:
  install dependency persis dari file requirements yang sama ke venv
  baru (bukan `-e .`, bukan pakai ulang venv dev dengan package sisa),
  konfirmasi CLI/entrypoint jalan dengan argumen persis yang ada di
  `CMD` Dockerfile (`--help` cukup untuk menangkap typo nama argumen),
  lalu deploy sungguhan ke Coolify dan CEK LOG CONTAINER-NYA (bukan cuma
  status "running") sebelum menganggap selesai -- dua bug nyata migrasi
  Coolify (missing sibling-module `COPY`, stdout ter-buffer) baru
  ketauan dari langkah terakhir ini, bukan dari langkah manapun sebelum
  deploy sungguhan.
- Validasi syntax file config secara lokal sebelum push:
  `python3 -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"`
  untuk TOML mana pun yang masih ada di repo, serupa untuk perubahan YAML
  apa pun di `.github/workflows/*.yml`, dan `docker build` itu sendiri
  sudah memvalidasi syntax Dockerfile (tidak perlu linter terpisah).
- Cek CI (`lint` + `neon-preview-branch`) hijau di PR sebelum merge --
  `neon-preview-branch` adalah satu-satunya yang menguji konektivitas
  Neon sungguhan, jadi PR adalah integration test sesungguhnya untuk
  perubahan DB, bukan Postgres lokal saja. **Ingat**: ini TIDAK menguji
  production sungguhan (lihat gap migrasi di atas) -- migration baru
  masih butuh `scripts/manual-migrate-neon.sh` manual setelah merge.
