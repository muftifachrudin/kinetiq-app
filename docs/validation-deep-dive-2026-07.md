# Deep-Dive Validasi & Teori v2: dari "meleset 2/10" menuju skor yang bisa dipertanggungjawabkan

Analisis mendalam (3 Juli 2026) atas hasil run validasi pertama terhadap data
production (`run-validation.yml` run #2: BTC/USDT perp 1h Binance, 8760 candle,
10 window walk-forward, **PF net > 1.3 cuma tercapai 2/10 window — kriteria
promosi GAGAL**). Dokumen ini menjawab tiga pertanyaan founder:

1. Kenapa hasilnya meleset — dan apakah itu berarti "teori tidak valid"?
2. Teori & skill apa yang dibutuhkan supaya sistem ini layak skor 8/10?
3. Apa peran data derivatives (funding, OI, long/short ratio, liquidation —
   via CoinGlass + Binance/Bybit) di teori yang matang?

Companion dari `docs/fib-gann-validation-brief.md` (bag. 22 menunjuk ke sini)
dan `docs/shadow-simulator-brief.md`. Semua angka di bawah dihasilkan dari
data yang benar-benar kita punya — bukan literatur, bukan asumsi.

---

## 0. Kesimpulan satu paragraf

**"Teori tidak valid" adalah diagnosis yang salah arah. Yang diuji kemarin
baru ±sepertiga dari teori founder** — satu timeframe (1h) saja tanpa bias
Weekly/Daily/4h (padahal multi-timeframe adalah inti PRD B.6 yang belum
diimplementasi), dengan bobot confidence hand-tuned yang ternyata
ANTI-prediktif, tanpa fee, tanpa konteks derivatives sama sekali. Hasil 2/10
itu BUKAN noise acak: kerugiannya terstruktur dan bisa dijelaskan (LONG
melawan tahun bear, SL struktural ke-wick 52%, band R:R 1.5–2 justru band
terburuk). Ketika tiga cacat yang paling murah diperbaiki disimulasikan ulang
terhadap 2.679 trade yang sama (bias trend + band R:R — keduanya komponen
teori founder sendiri, bukan ide baru), PF pooled naik dari 0.97 → 1.30
(1.13 setelah taker fee), konsisten di 4 seri (BTC/ETH × Binance/Bybit).
Jalan ke 8/10 itu ada, terukur, dan sebagian besar berupa menyelesaikan
apa yang memang sudah ada di roadmap — bukan mengganti teori dari nol.

---

## 1. Metodologi round analisis ini (supaya bisa direplikasi/dibantah)

- **Replikasi 4 seri**: pipeline yang sama persis dengan run CI
  (`signal_runner.generate_signals()` → `trade_simulator.simulate_trades()`
  → `metrics.compute_metrics()`, config walk-forward yang sama: anchored,
  train 1 bulan, test 1 bulan, embargo 1 hari) dijalankan terhadap 4 seri
  penuh 1 tahun dari tabel `ohlcv` production: **BTC & ETH × Binance &
  Bybit, 8.763 candle 1h per seri** (2025-07-03 → 2026-07-03).
  - 1 perbedaan metodologis kecil & disengaja: sinyal di-generate SEKALI
    atas seri penuh (jalan `as_of` `generate_signals()` sudah strictly
    causal, jadi sinyal per-bar identik dengan re-slicing per window) —
    bedanya hanya trade di tepi window yang tadinya censored kini resolve
    dengan data lanjutan. Angka BTC-Binance cocok dengan run CI (2/10
    window lolos, pola PF per window sama), konfirmasi replikasi benar.
- **Overlay derivatives**: CoinGlass Hobbyist, 399 hari harian untuk BTC &
  ETH: price, OI aggregated, funding (Binance & Bybit terpisah), taker
  buy/sell, global long/short account ratio, top-trader long/short position
  ratio, liquidation aggregated. Join per tanggal-entry trade.
  - **Terkonfirmasi eksplisit round ini: interval `1h` ditolak HTTP 403 di
    plan Hobbyist** — klaim "Hobbyist = daily-only" di brief bag. 9 naik
    status dari "asumsi yang belum diverifikasi" jadi "diverifikasi
    langsung".
- **Kejujuran statistik**: semua filter yang diuji ulang bersifat kausal
  (pakai data yang tersedia saat entry) KECUALI satu diagnostic yang
  sengaja lookahead dan dilabeli begitu (bag. 3-F9). Empat seri BUKAN 4
  sampel independen (Binance vs Bybit aset sama ~73% sinyalnya identik) —
  efektifnya ini ~2 sampel aset. Semua temuan derivatives = 1 tahun = 1
  rezim makro (dominan bear), belum teruji lintas rezim.

---

## 2. Replikasi: apakah kegagalan 2/10 itu karena data, noise, atau teori?

| Seri | Sinyal | Window lolos PF>1.3 | PF pooled (gross) | Win rate |
|---|---|---|---|---|
| Binance BTC | 669 | 2/10 | 1.086 | 39.0% |
| Bybit BTC | 655 | 3/10 | 1.120 | 39.7% |
| Binance ETH | 685 | 0/10 | 0.874 | 38.7% |
| Bybit ETH | 674 | 1/10 | 0.905 | 39.5% |

- **Cross-venue: konsisten.** Jaccard overlap sinyal Binance-vs-Bybit 72.9%
  (BTC) / 73.8% (ETH); PF per venue hampir identik. Artinya: hasil jelek
  itu BUKAN karena noise data satu bursa — mekanismenya robust, teorinya
  (dalam bentuk yang diuji) yang lemah. Menjawab pertanyaan "diuji di dua
  bursa berbeda": sudah, dan hasilnya saling mengonfirmasi.
- **Cross-asset: TIDAK generalize.** BTC marginal (PF ~1.1), ETH rugi
  (PF 0.87–0.90). Teori yang matang harus menjelaskan/mengatasi ini, bukan
  hanya di-tune untuk BTC.
- **Perp, bukan spot** — konfirmasi untuk pertanyaan founder: semua data &
  backtest ini `BTC/USDT:USDT` / `ETH/USDT:USDT` = **USDT-M perpetual**.
  Spot belum pernah diuji sama sekali.

## 3. Sepuluh temuan (F1–F11), dari yang paling merusak

**F1 — Confidence score sekarang ANTI-prediktif.** Pearson r(confidence,
return) = **-0.054**. Bucket confidence <0.5: PF 2.06 (n=67); 0.5-0.65:
PF 1.11; 0.65-0.75: PF 0.87; ≥0.75: PF 0.94. Sinyal yang sistem anggap
paling meyakinkan justru berkinerja lebih buruk dari yang paling ragu.
Bobot `ConfluenceWeights` hand-tuned (0.25/0.35/0.15/0.15/0.10) menyesatkan
— dan ini persis yang brief bag. 10 sebut "overfit ke intuisi". **Blocker
lama Part #2 ("belum ada data untuk fitting") SUDAH TIDAK ADA**: backtest
ini sendiri menghasilkan 2.679 sampel berlabel triple-barrier — itu
dataset fitting yang selama ini ditunggu.

**F2 — Tidak ada bias higher-timeframe, dan itu terlihat persis di P&L.**
LONG: PF 0.84 (rugi). SHORT: PF 1.12. Tahun data ini bear (drift BTC
negatif di 8/10 window; -12% s/d -18% di beberapa bulan). Sistem menembak
LONG melawan tren besar dengan frekuensi sama seperti SHORT karena
`signal_runner` sengaja masih single-timeframe dan slot `regime_alignment`
masih stub 1.0. Multi-timeframe confluence (Weekly→Daily→4h→1h, bobot
besar→kecil) adalah bagian PRD B.6 & bag. 2e yang belum dibangun — jadi
yang gagal kemarin bukan "teori founder", melainkan versi terpotongnya.

**F3 — SL struktural di-wick-hunt.** 52% trade (1.385/2.679) mati kena SL;
trade berumur ≤5 bar PF 0.36; 6-12 bar PF 0.60; TAPI yang bertahan 13-20
bar PF 2.16, dan outcome TIMEOUT (tidak kena TP/SL sampai 20 bar) PF 5.56
dengan mean +0.78%. Tesisnya sering benar arah — posisinya yang mati
duluan. SL "di balik swing + buffer 0.25-0.5×ATR" masih terlalu dekat/
obvious di 1h. Ini konsisten dengan konsep wick-rejection/stop-hunt yang
sudah ada di brief bag. 3 tapi belum jadi pertahanan SL.

**F4 — Band R:R 1.5–2 adalah band TERBURUK.** rr<2: PF 0.76; rr 2-3:
PF 1.09; rr 3-5: PF 1.29; rr≥5: PF 0.89 (lottery ticket). Gate R:R ≥1.5
yang sekarang justru meloloskan band yang paling merusak. Menaikkan gate ke
≥2.0 + cap <5.0 adalah perubahan satu-angka dengan efek besar.

**F5 — Fee belum dihitung, dan itu material.** `trade_simulator.py`
funding-aware tapi GROSS terhadap trading fee. Mean per trade baseline
-0.024%; round-trip taker-taker Binance VIP0 = 0.10% → mean jadi -0.124%,
PF 0.97 → 0.85. Untuk holding rata-rata 11 jam, funding cost justru sepele
(median ~0.003%/8h ≈ 0.006% per trade) — **biaya yang membunuh sistem
intraday 1h itu FEE, bukan funding**. Paper-vs-real gap #1 yang paling
murah ditutup: bikin simulator fee-aware.

**F6 — OI sebagai "bahan bakar": benar secara deskriptif, lemah secara
prediktif.** Replikasi teori founder di 399 hari × 2 koin (vs probe lama
89 hari × 1 koin): hari fuel-confirmed bergerak **1.80× (BTC) / 2.71×
(ETH)** lebih jauh dari hari unfueled — replikasi kuat, konsisten, dua
koin. TAPI versi prediktifnya (fuel hari H → |gerak| hari H+1) tipis:
1.61% vs 1.46% (BTC). Dan di-join ke trade backtest: fuel-confirmed vs
unfueled di hari entry TIDAK membedakan hasil trade (PF 0.97 vs 0.96).
**Kesimpulan: OI-fuel adalah indikator koinsiden (bagus untuk MEMBACA hari
yang sedang berjalan / konteks regime), bukan prediktor arah untuk entry
timing.** Jangan dijadikan bobot arah di confluence.

**F7 — Derivatives positioning = sinyal contrarian kecil tapi konsisten.**
- Funding tinggi (≥p90) BTC → next-day mean **-0.45%** (n=47); ETH tidak
  menunjukkan pola sama (+0.16%) — sinyal ada tapi asset-specific.
- Global long/short account ratio ≥p90 (retail crowded long) → next-day
  negatif; join ke trade: **SHORT saat crowd long: PF 1.17; LONG saat crowd
  long: PF 0.79**. Fade-the-crowd bekerja pelan tapi searah di dua koin.
- Top-trader vs global divergence: saat top-position ratio < global ratio
  (smart money kurang long dibanding kerumunan), next-day mean -0.22%
  (BTC) / -0.14% (ETH) — konsisten "ikuti top trader, lawan kerumunan".
- **Liquidation cascade: 20/20** hari long-liquidation terbesar (top-10 per
  koin) closing turun. Menjawab intuisi founder soal "margin/leverage
  tinggi bikin market tidak predictable": data bilang kebalikannya —
  leverage berkerumun justru bikin gerak MAKIN searah & tajam (cascade),
  dan itu terukur. Yang benar dari intuisi itu: posisi KITA yang
  ber-leverage tinggi jadi makin rapuh persis di hari-hari itu (nyambung ke
  `max_safe_leverage` + hard cap di shadow-simulator-brief bag. 5).

**F8 — Diagnostic same-day drift (SENGAJA lookahead, bukan strategi):**
trade yang arahnya searah drift harian hari itu: PF 3.46 / WR 62%; yang
melawan: PF 0.39 / WR 25%. Ini bukan rule yang bisa ditrade (drift hari
belum selesai saat entry) — ini BUKTI KUANTITATIF bahwa nasib sinyal 1h
ditentukan oleh alignment arah pasar yang lebih besar, alias bukti F2 dari
sisi lain.

**F9 — Versi kausal dari F8 benar-benar bekerja.** Filter yang bisa
dihitung saat entry, diuji ulang pada 2.679 trade yang sama:
- Searah SMA200-1h (proxy tren ~8 hari): PF 1.08 vs melawan 0.90.
- Searah SMA50-1h (~2 hari): PF 1.19 vs melawan 0.87.
- Searah drift kemarin (harian): PF 1.16 vs melawan 0.83.

**F10 — Kombinasi dua perbaikan implementable: PF 0.97 → 1.30.**
`searah-SMA200 DAN rr∈[2,5)`: n=622, **PF 1.298 gross / 1.131 setelah
taker fee 0.10%**, konsisten di kedua venue (1.28/1.32) dan positif di
kedua aset (BTC 1.50, ETH 1.18); per bulan kalender: positif di 9/12 bulan.
**Caveat yang wajib diingat: ini in-sample** — filternya dipilih setelah
melihat data ini, jadi angka 1.30 adalah HIPOTESIS untuk diuji
out-of-sample, bukan hasil final. Yang membuatnya bukan data-mining liar:
dua-duanya bukan ide baru — HTF bias adalah PRD B.6/bag. 2e yang belum
dibangun, dan R:R gate memang sudah ada (cuma angkanya salah band).

**F11 — Temuan integritas data (di luar strategi, tapi penting):
`trade_annotation` production KOSONG.** `pg_relation_size`=0 byte (heap
tidak pernah ditulis), `instrument` cuma 4 baris (import seharusnya
auto-provision 53 simbol) — padahal brief bag. 21 mencatat import 276
posisi "sukses & diverifikasi count 276" pada 3 Juli. Branch `production`
(dibuat 1 Juli) adalah satu-satunya branch di project Neon ini. Kemungkinan:
transaksi Neon SQL Editor ter-rollback setelah verifikasi, atau verifikasi
terjadi di session/project berbeda. **Action founder: jalankan ulang file
`--emit-sql` di Neon SQL Editor dan verifikasi `count(*)` dari SESSION
BARU yang terpisah.** Tanpa ini, agreement-rate, shadow_pair, dan semua
kalibrasi berbasis trade real tetap buntu — dan analisis "behavior trader
dari histori real" yang diminta founder round ini juga belum bisa dikerjakan.

**RESOLVED 2026-07-03 (sesi implementasi Fase 1)**: akar masalahnya BUKAN
transaksi database yang rollback -- paste manual 775-baris file `--emit-sql`
ke Neon SQL Editor via browser mobile silently truncate jauh di bawah ukuran
aslinya (konsisten terpotong ~140-150 baris apa pun ukuran file). Fix: file
dipecah jadi chunk kecil untuk sebagian (row 1-120 via Neon SQL Editor manual),
lalu sisanya (row 121-276) dieksekusi langsung dari sandbox via endpoint
HTTP-SQL Neon bentuk `{"queries": [...]}` — satu request 159 query berhasil
penuh, diverifikasi count terpisah: `trade_annotation`=276, `instrument`=55.
Detail lengkap: `docs/fib-gann-validation-brief.md` bag. 23 update, CLAUDE.md.

---

## 4. Teori v2 — rumusan yang matang (berdasarkan bukti di atas)

Teori v1 yang implisit di kode sekarang: *"sentuhan harga ke level
fib/gann yang confluence = sinyal entry berbobot confidence."* Data bilang
itu tidak cukup. Teori v2, dirumuskan supaya tiap klausa bisa diuji dan
digugurkan:

> **(a) Level fib/gann yang confluence menandai ZONA REAKSI — tempat
> probabilitas reversal/bounce meningkat — bukan sinyal arah.**
> Buktinya: mekanisme deteksinya robust lintas bursa (F: Jaccard 73%,
> PF nyaris identik), tapi tanpa arah dia hanya koin-flip yang kalah fee.
>
> **(b) ARAH datang dari struktur pasar timeframe di atasnya.** Sinyal 1h
> hanya boleh percaya diri kalau searah bias Daily/4h (dan kelak Weekly).
> Buktinya: F2, F8, F9 — semua ukuran alignment tren memisahkan PF 1.1-3.5
> vs 0.4-0.9.
>
> **(c) Konteks derivatives menentukan KUALITAS zona, sebagai faktor skor
> contrarian-kecil, bukan gate:** crowded-long (global L/S tinggi, funding
> ≥p90, top-trader kurang long dari kerumunan) menurunkan kualitas LONG dan
> menaikkan kualitas SHORT — dan sebaliknya. OI-fuel dipakai untuk membaca
> rezim volatilitas (hari fuel = gerak 1.8-2.7× lebih besar → sizing/SL
> lebih longgar), BUKAN untuk arah. Buktinya: F6, F7.
>
> **(d) SL harus berada di luar jangkauan hunting likuiditas, dan
> ekspektasi dimonetisasi hanya pada struktur R:R 2-5.** Buktinya: F3, F4 —
> separuh kematian sistem adalah wick ke SL yang tesisnya belum salah, dan
> band R:R di bawah 2 menyumbang kerugian bersih.
>
> **(e) Semua bobot antar-faktor BUKAN opini — di-fit dari label
> triple-barrier dengan regularisasi, di-refit per walk-forward window, dan
> sebuah faktor hanya bertahan kalau menaikkan AUC/PF out-of-sample.**
> Buktinya: F1 — bobot opini terbukti anti-prediktif; dan dataset untuk
> fitting kini sudah ada (2.679 label, bertambah tiap run).
>
> **(f) Edge yang tersisa harus survive biaya REAL: taker fee dua sisi,
> slippage, funding aktual per-8h, dan margin/leverage constraint.**
> Buktinya: F5 — fee saja mengubah tanda mean return; dan shadow-simulator
> brief sudah menyiapkan kerangkanya (liquidation-aware sim + divergence
> attribution) tinggal diberi makan data.

Prinsip bag. 10 (gate keras vs faktor skor) TETAP berlaku: (b)–(d) masuk
sebagai **faktor skor yang di-fit**, bukan gate AND baru — dengan satu
pengecualian yang sadar: R:R band (d) memang gate, karena dia sudah gate
sekarang; yang berubah hanya angkanya (1.5 → 2.0, plus cap 5.0), dan itu
pun harus dikonfirmasi out-of-sample dulu.

## 5. Apa artinya "skor", dan jalan dari ~3/10 sekarang ke 8/10

Supaya "8/10" bukan angka perasaan, definisikan rubric-nya eksplisit.
Posisi sekarang menurut rubric ini: **±3/10** (pipeline end-to-end
terverifikasi + replikasi lintas bursa jalan; edge belum terbukti; skor
internal anti-prediktif; biaya belum lengkap).

| Skor | Syarat OBJEKTIF (kumulatif) |
|---|---|
| 4/10 | Simulator fee-aware; baseline & semua eksperimen dilaporkan net-of-fees. `trade_annotation` terisi ulang & terverifikasi (F11 beres). **SELESAI 2026-07-03** (lihat `docs/sonnet5-implementation-roadmap.md` Fase 1) — verifikasi data real BTC/Binance 1-tahun: PF gross rata-rata antar-window ~1.10 → PF net-fees ~0.92, konsisten arah dengan F5. `trade_annotation` sekarang **276 baris**, `instrument` **55** — F11 RESOLVED (lihat catatan di F11 di atas). |
| 5/10 | HTF bias (Daily/4h dari resample 1h) masuk sebagai faktor; R:R band di-set dari data; PF net-of-fees pooled > 1.1 di ke-4 seri pada data yang sama (sanity, masih in-sample). |
| 6/10 | Part #2 jalan: bobot di-fit logistic + L1/L2 pada label triple-barrier, refit per window walk-forward; confidence hasil fit berkorelasi POSITIF dengan outcome secara out-of-sample (bukti skor sudah informatif). |
| 7/10 | Kriteria promosi asli brief bag. 7 tercapai di BTC pada walk-forward penuh: PF net > 1.3 di ≥2/3 window — net of fees. |
| 8/10 | Kriteria yang sama tercapai di BTC DAN ETH, kedua venue; + agreement-rate vs trade real mulai terukur; + ≥50 shadow pair terkumpul (cold-start ML risk envelope terpenuhi). |
| 9/10 | 3+ bulan shadow/live kecil: PF real net ≥ 0.7× PF backtest, fidelity score rolling ≥70, tidak ada pelanggaran hard cap leverage. |
| 10/10 | Bertahan lintas rezim (bull & bear & range terpisah di ≥2 tahun data), edge tetap positif setelah SEMUA biaya di ukuran posisi nyata. |

Kejujuran yang perlu ditulis sekali dan tidak diulang-ulang: **10/10 dalam
arti "pasti profit" tidak eksis secara sains.** 10/10 di rubric ini berarti
"proses validasinya tidak bercela dan edge-nya bertahan di semua uji yang
bisa kita lakukan" — probabilistik, bukan garansi. Paper trading tanpa
uang memang beda dengan eksposur real — justru karena itu jalur 8→10
di rubric ini seluruhnya lewat shadow-pair & fidelity (mengukur gap
paper-vs-real per komponen), bukan lewat backtest yang makin panjang.

## 6. Skill yang dibutuhkan

### 6a. Skill kode (urutan prioritas, semua selaras roadmap yang ada)

1. **Fee-aware `trade_simulator.py`** (F5) — parameter maker/taker bps per
   venue, dipotong di `net_return_pct`. Kecil, efeknya ke semua angka.
2. **`htf_bias.py`** (F2/F9) — resample 1h→4h/Daily, lalu REUSE
   `market_structure.trend_bias()` yang sudah ada di timeframe hasil
   resample; output slot skor ala `regime_alignment` (bukan gate). Ini
   implementasi pertama dari multi-timeframe PRD B.6 — bagian teori founder
   yang kemarin belum ikut diuji.
3. **Dump komponen skor per-faktor di `signal_runner`** (F1) — sekarang
   cuma `confidence` final yang tersimpan; fitting butuh nilai
   swing_quality/fib_gann/volume/wick/structure/htf/derivatives per sinyal.
4. **Part #2 fitting** (F1) — logistic regression + regularisasi pada label
   triple-barrier, refit per window (`packages/backtest-core` windows),
   evaluasi AUC/Brier out-of-sample; gantikan `ConfluenceWeights` default
   dengan hasil fit. Dataset 2.679 label sudah ada dari round ini.
5. **`derivatives_context.py`** (F6/F7) — fetch harian CoinGlass (funding
   percentile per-koin, global L/S ratio, top-vs-global divergence, flag
   liq-cascade & fuel-quadrant kemarin) sebagai faktor skor + konteks
   sizing. Harian sudah cukup (Hobbyist), TIDAK butuh upgrade tier untuk
   mulai; granularity jam menyusul via ingestion sendiri.
6. **Backfill `funding_rate` & `open_interest` native 8h/1h dari
   Binance/Bybit** (worker ingestion sudah jalan untuk ohlcv — tinggal
   diperluas) — supaya funding cost per-trade dihitung dari event aktual
   (holding 11 jam melewati 1-2 event), dan supaya fuel/positioning bisa
   dites di granularity jam (yang CoinGlass Hobbyist tidak kasih, 403).
7. **Re-import `trade_annotation` + kolom `signal_id`** (F11 + migration
   0005 follow-up) — buka jalur agreement-rate & shadow_pair yang sekarang
   buntu.
8. **SL anti-hunt eksperimen** (F3) — varian buffer lebih lebar / berbasis
   struktur likuiditas, diuji HEAD-TO-HEAD vs SL sekarang di harness yang
   sama sebelum diadopsi. Jangan diubah diam-diam.

### 6b. Skill proses/trader (menjawab "eksposur real terasa beda")

1. **Disiplin mencatat**: tiap trade real lewat `log_trade_annotation.py`
   dengan `leverage`, `margin_mode`, `exit_reason_real` terisi — tanpa ini
   divergence attribution cuma bisa menghitung entry slippage.
2. **Target 50 shadow pair** sebelum percaya angka fidelity/ML apapun
   (cold-start rule shadow-brief bag. 5 — tetap berlaku).
3. **Leverage adalah output, bukan input** (shadow-brief bag. 5): hard cap
   manual per simbol tetap di atas `max_safe_leverage` formula — data
   liquidation-cascade round ini (20/20) adalah alasan empirisnya.
4. **Baca konteks derivatives sebelum sesi trading, bukan saat entry**:
   funding percentile + L/S ratio + fuel kemarin itu data HARIAN — dipakai
   untuk menetapkan bias & sizing hari itu, bukan untuk menimpa sinyal
   per-jam.
5. **Perlakukan angka in-sample sebagai hipotesis** — termasuk PF 1.30 di
   dokumen ini sendiri. Keputusan promosi hanya dari walk-forward
   out-of-sample (kriteria bag. 7 brief utama, net of fees).

## 7. Batasan analisis ini (supaya tidak dikutip melebihi bobotnya)

- 1 tahun data = dominan SATU rezim (bear). Filter tren yang menyelamatkan
  P&L di tahun bear bisa underperform di tahun choppy — makanya rubric
  10/10 minta lintas rezim.
- 4 seri ≈ efektif 2 sampel aset (venue overlap 73%).
- Perbandingan berganda: puluhan irisan dites; temuan kecil yang belum
  direplikasi lintas aset (mis. sesi off-hours PF 1.54, funding-ekstrem
  ETH yang tidak cocok BTC) JANGAN diberi bobot dulu.
- Barrier check masih granularity 1h (aturan konservatif same-candle=SL
  tetap dipakai); data <1h belum ada di ohlcv.
- Semua PF di dokumen ini gross-of-fees kecuali disebut "net".

---

## 8. Ronde 2 (4 Juli 2026) — Exit-management & fee lab: 3 lever nyata, 5 hipotesis terbantah

Riset lanjutan atas permintaan founder ("naikkan PF net secara nyata,
bukan sekadar tunggu data forward"). Metode: replay ke-2.679 trade yang
sama (4 seri, config default) di bawah aturan exit alternatif — script
`validation/deep_dive_2026_07/exit_lab.py`, aturan konservatif
same-candle=SL dipertahankan, managed-stop hanya bertindak di close bar
(no lookahead), semua angka net-of-fees. "STACK" = subset kausal
aligned-SMA200 & rr∈[2,5) (aproksimasi stack terbaik saat ini). Konteks
posisi: setelah PR #82, gate trend-alignment sudah mengangkat BTC ke PF
net 1.185 (full-set) — ronde ini mencari lever di ATAS itu, terutama
untuk ETH yang masih buntu.

**Status kejujuran: ini mining pass ke-4 atas tahun data yang sama.**
Semua angka di bawah = hipotesis in-sample untuk diuji OOS di harness,
KECUALI lever fee yang sifatnya mekanis (pengurangan biaya deterministik,
bukan taruhan pasar — risikonya fill probability, bukan statistik).

### F12 — Eksekusi maker (entry limit + TP limit): lever paling andal, naik di SEMUA irisan

Akuntansi fee maker-entry + maker-TP (stop/timeout tetap taker; Binance
VIP0: maker 2bps vs taker 5bps) menaikkan PF di setiap varian dan setiap
irisan tanpa pengecualian, +0.04 s/d +0.08 PF:

| Irisan | taker-taker | maker-entry/TP | CI90 (maker) |
|---|---|---|---|
| STACK pooled (n=622) | 1.131 | **1.187** | [1.000, 1.396] |
| STACK BTC (n=314) | 1.261 | **1.338** | [1.068, 1.655] |
| STACK ETH (n=308) | 1.049 | **1.092** | [0.871, 1.383] |

Logika fill JUJUR yang wajib dipakai saat ini masuk harness: sinyal fire
saat harga MENYENTUH level → limit entry di level itu terisi saat harga
menembusnya (probabilitas tinggi tapi bukan 100% — antrian di touch
persis tidak pasti); TP limit butuh penetrasi, bukan sekadar touch → rule
fill konservatif: `high > tp` strict (bukan `>=`), atau penetrasi minimal
1 tick. Downside case: limit entry tidak terisi = trade tidak terjadi =
kehilangan sebagian sinyal, BUKAN kerugian.

### F13 — Asimetri exit-style per aset: BTC "tahan noise", ETH "potong cepat" — lever ETH nyata PERTAMA

Semua angka maker-fee, subset STACK, CI90 bootstrap 3.000 iterasi:

| Varian exit | STACK BTC | STACK ETH |
|---|---|---|
| baseline (TP1/SL/timeout20) | 1.338 [1.07-1.66] | 1.092 [0.87-1.38] |
| + breakeven @ +1R | **1.383 [1.09-1.73]** | 1.100 (nihil) |
| + momentum-exit @ -0.3R close | 1.011 (RUSAK) | **1.272 [1.00-1.63]** |
| + momentum-exit @ -0.5R close | 1.142 | 1.199 |
| + momentum-exit @ -0.7R close | 1.274 | 1.118 |

Polanya monoton dan BERLAWANAN ARAH di dua aset: makin ketat
momentum-exit makin bagus ETH dan makin rusak BTC. Ini koheren dengan
karakter aset yang sudah terukur (vol harian ETH 2.5-3% vs BTC 1.5% —
close melawan -0.3R di ETH lebih sering berlanjut ke SL; BTC lebih sering
mean-revert). **Framing untuk F8 nanti: threshold momentum-exit BUKAN
dial per-simbol bebas (melanggar prinsip no-per-symbol-tuning) — dia
kandidat fungsi dari properti aset terukur (normalized vol/ATR%), yang
bisa diuji generalisasinya begitu universe bertambah.**

Best stack in-sample per aset setelah ronde ini (maker-fee):
- **BTC: aligned + rr[2,5) + BE@1R → PF 1.383, CI90 bawah 1.09** (di atas
  1.0!) — dan ini BELUM dikombinasikan dgn temuan gate #82 di harness.
- **ETH: aligned + rr[2,5) + mom@0.3R → PF 1.272, CI90 bawah ~1.00** —
  pertama kalinya ETH menyentuh wilayah kriteria masuk-shadow.

### F14 — Lima hipotesis exit TERBANTAH (jangan dikerjakan ulang)

1. **Trailing stop 1R setelah +1R**: netral s/d merusak (STACK BTC 1.19
   vs baseline 1.34). 2. **Time-stop 8 bar** (exit kalau belum profit):
   merusak di semua irisan (STACK pooled 1.03). 3. **Timeout 40 bar**:
   nihil di STACK (+0.00-0.01); +0.03 hanya di set unfiltered.
   4. **TP lebih dekat 0.7× / lebih jauh 1.5×**: dua-duanya menurunkan PF
   di STACK. 5. **BE untuk ETH**: nihil (1.092→1.100).
   
   **Pelajaran metodologis penting**: TIMEOUT PF 5.56 dari temuan F3 itu
   **efek seleksi** (conditional on survival 20 bar), BUKAN alpha yang
   bisa dipanen ex-ante — memperpanjang timeout tidak menangkap apa-apa
   karena populasi yang bertahan memang sudah tersaring. Contoh konkret
   kenapa "slice yang bagus" ≠ "rule yang bagus".

### Instruksi uji OOS untuk harness (DEV)

Tiga A/B pre-registered di `rr_sl_experiment.py`/`campaign.py`, di atas
config kandidat F5 + gate alignment (#82), walk-forward penuh, semua
net-of-fees, funnel dilaporkan: (a) fee model maker dgn rule fill
konservatif (F12) — ini juga butuh dukungan `fee_entry/exit` per-outcome
di simulator; (b) BE@1R, BTC saja dulu; (c) momentum-exit @0.3R/0.5R,
ETH saja dulu — dan JANGAN diadopsi lintas aset tanpa uji generalisasi
properti-vol (F13). Kriteria keputusan tetap bag. 7 + kriteria
masuk-shadow F7 Tahap 2 (PF pooled > 1.1, CI bawah > 1.0).
