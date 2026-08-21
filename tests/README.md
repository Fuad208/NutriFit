# Pengujian NutriFit

Sebelas skrip verifikasi yang bisa dijalankan langsung, tanpa pytest dan **tanpa
menyentuh data asli**.

```bash
.venv/Scripts/python.exe tests/test_password.py           # hashing & migrasi kata sandi
.venv/Scripts/python.exe tests/test_image_check.py        # pemeriksa gambar (throttle vs mati)
.venv/Scripts/python.exe tests/test_recommender.py        # aturan menu & porsi
.venv/Scripts/python.exe tests/test_meal_plan_rules.py    # aturan slot & penukaran
.venv/Scripts/python.exe tests/test_food_filter.py        # saringan menu layak rekomendasi
.venv/Scripts/python.exe tests/test_clustering_metrics.py # metrik & kestabilan klaster
.venv/Scripts/python.exe tests/test_evaluation_metrics.py # Metode Siku, Gower, MAP & NDCG
.venv/Scripts/python.exe tests/test_claims.py             # klaim harian
.venv/Scripts/python.exe tests/test_delete_confirmation.py# konfirmasi hapus riwayat
.venv/Scripts/python.exe tests/test_app_smoke.py          # render halaman (Streamlit AppTest)
.venv/Scripts/python.exe tests/test_legacy_records.py     # kompatibilitas record lama
```

## Bagaimana data asli dilindungi

Penyimpanan aplikasi cuma satu (Supabase), jadi skrip uji tidak punya penampung
sementara di luar database. Isolasinya dilakukan di tingkat **schema Postgres**: `tests/_isolasi.py` memanggil `pakai_schema_uji(<nama>)` yang mengisi
env `POSTGRES_SCHEMA` dengan schema sekali-pakai (`uji_smoke`, `uji_claims`, ...),
membuangnya lebih dulu supaya mulai dari nol, lalu membuangnya lagi lewat
`atexit` setelah selesai — termasuk kalau pengujiannya gagal di tengah.

Tabelnya dibentuk oleh `ensure_schema()` yang sama dengan yang dipakai aplikasi,
jadi yang diuji benar-benar skema sesungguhnya. `search_path` koneksi uji sengaja
**tidak** menyertakan `public`: kalau ada tabel yang belum terbentuk, query-nya
gagal terang-terangan alih-alih diam-diam membaca data asli.

Konsekuensinya, skrip yang menyentuh database **butuh koneksi internet**.
`test_image_check.py`, `test_recommender.py`, `test_meal_plan_rules.py`,
`test_clustering_metrics.py`, dan `test_evaluation_metrics.py` tidak menyentuh
jaringan sama sekali (respons HTTP dipalsukan, dataset dibaca dari CSV, dan
metrik diuji pada data buatan).

Skrip uji **tidak boleh dijalankan berbarengan** dengan notebook pengujian:
keduanya memakai nama schema sekali-pakai yang sama (`uji_smoke`, ...), jadi yang
satu bisa membuang schema milik yang lain di tengah jalan dan membuat pengujian
gagal tanpa ada yang salah pada kodenya.

## Apa yang dijamin tiap skrip

### `test_recommender.py`
Menguji klaim-klaim yang dipakai di laporan:

- proporsi slot berjumlah tepat 1,0 dan **total kuota keempat slot = target
  kalori harian**, diuji pada target 1.200-3.500 kkal;
- **gramasi** tiap item benar-benar hasil `(kuota kalori ÷ kalori per 100 g) × 100`;
- **Volumetric Sanity Check** ditegakkan: tidak ada porsi di luar 50-450 g;
- slot camilan **tidak pernah** berisi makanan berat, termasuk setelah 20 kali
  penukaran beruntun;
- **Dynamic Portion Constraint**: item pengganti mempertahankan kuota kalori
  item yang diganti, jadi total harian tidak berubah;
- filter kategori bekerja untuk tiap kategori tanpa menyisakan slot kosong.

### `test_claims.py`
- klaim menu menambah kalori & makro, dan **makro diskalakan ke gramasi porsi**
  (bukan nilai per 100 g mentah);
- membatalkan klaim mengurangi kembali;
- menyusun menu baru di sore hari **tidak menghapus** klaim pagi;
- klaim latihan menambah perkiraan kalori terbakar, dan hilang saat dibatalkan;
- klaim atas item yang tidak ada di rencana hari itu ditolak.

### `test_password.py`
- hash baru berformat `$argon2id$` dan tidak memuat kata sandinya;
- salt acak: dua hash untuk kata sandi yang sama menghasilkan nilai berbeda;
- akun lama ber-hash SHA-256 **masih bisa login**, lalu otomatis dimigrasi ke
  Argon2id dan hash lamanya terhapus dari database;
- kata sandi **polos** ditolak — fallback lama sudah ditutup.

### `test_image_check.py`
Menjaga sifat yang membuat **jumlah menu bisa direproduksi**. Aplikasi membuang
menu yang gambarnya tidak bisa ditampilkan; pemeriksaannya menembak ratusan URL
sekaligus, dan host seperti `upload.wikimedia.org` membalas **HTTP 429** kalau
diserbu. Dulu 429 diperlakukan sama dengan 404 — menunya dibuang, dan hasilnya
disimpan ke cache selama 7 hari — sehingga jumlah menu berubah-ubah antar
eksekusi walaupun datanya sama persis. Skrip ini memastikan:

- 429/500/502/503/504 → menu **dipertahankan** (server hidup, hanya menolak);
- 404/410/400 → menu dibuang (gambarnya memang tidak ada);
- dugaan akibat throttle **tidak ditulis** ke cache disk, jadi diperiksa lagi nanti;
- gambar yang benar-benar mati tetap disimpan supaya tidak dicek berulang;
- 403/405 tetap dicoba ulang lewat GET (perilaku lama dipertahankan).

### `test_app_smoke.py`
Menjalankan `app.py` sungguhan lewat `streamlit.testing.v1.AppTest`:

- Beranda, Rekomendasi Menu, Rekomendasi Latihan, dan Tutorial Latihan render
  tanpa exception (termasuk jalur "tutorial tidak ditemukan");
- pilihan kategori muncul dan keempat slot tampil setelah "Buat Menu";
- checkbox klaim menu **dan** latihan muncul di dashboard;
- mencentang latihan benar-benar mengubah keterangan pada kartu
  Target Kalori Harian;
- menekan **Tukar Sekarang** benar-benar mengganti item, tidak mengubah total
  kalori harian, dan tidak pernah memasukkan makanan berat ke slot camilan;
- langkah pelaksanaan di halaman tutorial tampil dalam bahasa Indonesia.

Skrip ini memakai subset data latihan yang namanya persis sama dengan dataset
tutorial supaya pencocokan fuzzy `exercises_with_video_tutorials` (O(n×m) atas
2.918 × 1.324 baris) tidak membuat pengujian berjalan lama.

### `test_evaluation_metrics.py`
Memeriksa **alat ukurnya sendiri**, sebelum alat itu dipakai menilai algoritma.
Ketiga alat baru gampang diimplementasikan setengah benar dan tetap mengeluarkan
angka yang terlihat masuk akal, jadi masing-masing diuji pada kasus yang
jawabannya sudah diketahui lebih dulu:

- **Metode Siku** menemukan siku di K yang memang dipatahkan sengaja, tidak
  bergeser saat satuan biaya dikali 1.000, dan tidak menemukan siku pada kurva
  lurus;
- **Gower Distance** cocok dengan hitungan tangan, simetris, berdiagonal nol,
  selalu di rentang 0-1, **tidak berubah oleh penskalaan** kolom numerik, dan
  tidak membagi nol pada atribut konstan;
- **Silhouette-Gower** dan **Calinski-Harabasz** memberi nilai tinggi pada label
  yang benar dan nyaris nol pada label yang diacak;
- **MAP** dan **NDCG** cocok dengan hitungan tangan ((1/1 + 2/3)/2 dan
  1,5 / (1 + 1/log₂3)), bernilai 1,0 pada susunan sempurna, selalu 0-1, dan
  pembanding acaknya reproducible pada seed yang sama.

### `test_legacy_records.py`
Menjaga **jalur naik-versi**. Database yang sudah berjalan memuat record menu dan
latihan yang dibuat sebelum kolom `Is_Snack`, `Food_Category`, `meal_slot`,
`slot_quota_calories`, dan `is_done` ada — dan sebelum distribusi slot diubah.
Halaman Rekomendasi Menu memulihkan record hari ini dari database secara otomatis,
jadi bentuk lama yang bikin error akan terlihat begitu aplikasi dibuka, bukan saat
tombol ditekan. Skrip ini memastikan:

- record lama (Camilan 1 item, distribusi 25/35/10/30) dipulihkan dan dirender utuh;
- preferensi berupa kata kunci bebas lama diabaikan, filter kategori kembali kosong,
  menunya tetap tampil;
- menekan **Tukar** pada item lama yang tidak punya `meal_slot` tetap berhasil —
  dan menukar makanan berat yang tersisa di slot Camilan menghasilkan camilan asli;
- dashboard membaca record lama dan menu maupun latihannya bisa diklaim
  walau `is_done` belum pernah ada di record itu.
