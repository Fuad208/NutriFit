# Catatan Desain NutriFit

Berkas ini menyimpan **alasan dan angka pengukuran** di balik keputusan desain sistem.
Sebelumnya seluruh isi berkas ini ditulis sebagai komentar panjang di dalam kode. Komentar di
kode kini dipangkas agar hanya menerangkan fungsi atau method yang bersangkutan, sedangkan
pembenaran dan tabel pengukurannya dipindahkan ke sini.

Dipakai sebagai rujukan saat sidang dan saat menulis Bab III dan Bab IV.

---

## 1. K-Means menu makanan: kenapa K = 4

`FOOD_CLUSTER_COUNT` di `src/recommender.py`.

K = 4 adalah **keputusan struktural**, bukan hasil Metode Siku. Pada 780 menu layak
rekomendasi, ruang lima fitur memberi kurva berikut.

| K | WCSS | Jarak ke garis | Silhouette | Calinski-Harabasz |
|---|------|----------------|------------|-------------------|
| 2 | 92,80 | 0,0000 | **0,4297** | 544 |
| 3 | 67,27 | 0,1601 | 0,4083 | 522 |
| 4 | 49,24 | 0,2474 | 0,4029 | 570 |
| 5 | 39,88 | **0,2501** | 0,3658 | 572 |
| 8 | 24,88 | 0,1309 | 0,3772 | **589** |

Ketiga kriteria menunjuk arah berbeda — siku ke 5, Silhouette ke 2, Calinski-Harabasz ke 8 —
sehingga tidak ada satu pun yang bisa dipakai sebagai pembenaran tunggal. Yang menentukan tetap
`MEAL_TEMPLATES`, yang membutuhkan peran gizi yang bisa diminta per slot.

K = 4 jauh lebih bisa dipertahankan daripada K = 3 yang dipakai sebelumnya: jaraknya ke garis
(0,2474) praktis menyamai titik siku di K = 5 (0,2501), selisih 0,0027 pada kurva yang landai,
sedangkan K = 3 tertinggal jauh di 0,1601. Klaster kelima yang ditawarkan siku juga bukan peran
baru — ia hanya memecah karbohidrat menjadi dua tingkat (202 kkal / 37 g karbo dan
382 kkal / 68 g karbo), sementara empat peran gizinya tetap sama.

### Keempat peran pada K = 4

| Peran | Watak | kkal | protein | lemak | karbo | g protein / 100 kkal | n |
|-------|-------|------|---------|-------|-------|----------------------|---|
| A | tinggi karbohidrat | 342 | 4,7 | 4,3 | 64,0 | 1,5 | 158 |
| B | protein ramping | 153 | 16,7 | 7,3 | 2,2 | 10,7 | 129 |
| C | rendah kalori | 110 | 2,2 | 1,4 | 18,2 | 2,1 | 392 |
| D | protein berlemak | 425 | 12,9 | 29,9 | 28,4 | 3,2 | 101 |

### Kenapa kepadatan protein menjadi fitur kelima

Kepadatan protein (gram protein per 100 kkal) adalah satu-satunya sumbu yang memisahkan protein
ramping dari protein berlemak. Selama fiturnya hanya empat makronutrien dalam nilai mutlak,
kelompok itu mustahil ditemukan berapa pun nilai K, karena kepadatan adalah rasio.

Akibat nyata sebelum fitur ini ada: 65 menu berprotein ramping seluruhnya tenggelam di klaster
rendah kalori bersama 498 menu lain, sementara klaster yang dinamai "tinggi protein" ternyata
63 % kalorinya berasal dari **lemak** (protein 23,5 g, lemak 23,8 g) — dan `MEAL_TEMPLATES`
memanggil klaster itu sebagai sumber protein di sarapan, makan siang, dan makan malam.

---

## 2. K-Prototypes: kenapa Fitness_Goal dibobot 3

`MEMBER_CATEGORICAL_WEIGHTS` di `src/recommender.py`.

Jarak K-Prototypes memberi tiap atribut kategorikal nilai 0 atau 1, yang terlihat adil tetapi
tidak. Atribut yang mudah dipisah mendominasi, dan atribut yang kelasnya timpang tenggelam.
Tanpa bobot, klaster anggota sebenarnya dibentuk oleh Gender (Cramér V = 0,897) — sedangkan
Fitness_Goal, yang justru menjadi **tujuan** segmentasi sistem ini, hanya 0,180. Akibatnya
168 anggota menerima mandat yang bertentangan dengan kategori IMT-nya sendiri.

| Bobot | K | Silhouette | Salah klaster | V Tujuan | V Gender | Langgar mandat |
|-------|---|------------|---------------|----------|----------|----------------|
| 1 | 5 | 0,3446 | 2,3 % | 0,180 | 0,897 | 168 |
| 2 | 5 | 0,3357 | 1,8 % | 0,665 | 0,329 | 0 |
| **3** | **5** | **0,3366** | **5,0 %** | **0,981** | **0,246** | **0** |
| 4 | 5 | 0,3373 | 5,3 % | 1,000 | 0,238 | 0 |
| 6 | 4 | 0,2833 | 0,3 % | 1,000 | 0,356 | 0 |

Bobot 2 sudah cukup menghapus seluruh pelanggaran mandat, tetapi **tidak** cukup memisahkan
tujuan: pada bobot 2 kelima klaster masih bercampur dan "Maintain Weight" tidak pernah mendapat
klaster sendiri — 135 anggotanya terserak di semua klaster. Pada bobot 3 hanya 2 dari 5 klaster
yang bercampur dengan total 7 anggota nyasar, dan "Maintain Weight" akhirnya punya klaster utuh
berisi 128 orang. Bobot 4 ke atas tidak menambah apa pun; pada bobot 6 nilai K malah runtuh ke 4
sehingga tiga sub-segmen "Lose Weight" melebur jadi dua.

**Harganya disebut apa adanya:** Silhouette-Gower turun tipis (0,3446 → 0,3366), tetapi titik
salah klaster naik dari 2,3 % ke 5,0 %. Itu wajar — begitu klaster dipaksa sejajar dengan tujuan,
tujuh atribut lain jadi kurang homogen di dalamnya, sedangkan Gower menimbang kedelapan atribut
setara. Yang dibeli dengan harga itu adalah kesejajaran tujuan 0,180 → 0,981 dan pelanggaran
mandat IMT 168 → 0.

---

## 3. K-Modes latihan: kenapa jarak Hamming dibobot

`categorical_attribute_weights()` di `src/recommender.py`.

Hamming memberi tiap atribut nilai 0 atau 1. Atribut yang isinya nyaris seragam hampir selalu
bernilai 0, jadi praktis tidak pernah ikut membedakan dua baris. Pada data latihan, `Type` 90 %
berisi "Strength" dan `Level` 92 % berisi "Intermediate", sehingga peluang keduanya menyumbang
jarak hanya 0,18 dan 0,16 — sedangkan `BodyPart` (16 kategori) dan `Equipment` (12 kategori)
menyumbang di atas 0,83. Efeknya klaster terbentuk hanya dari dua atribut.

Bobot hasil perhitungan pada dataset ini:

| Atribut | Kategori | Terbanyak | Bobot |
|---------|----------|-----------|-------|
| Type | 7 | Strength (90 %) | 1,549 |
| Level | 3 | Intermediate (92 %) | 1,795 |
| BodyPart | 16 | Abdominals (22 %) | 0,320 |
| Equipment | 12 | Body Only (30 %) | 0,335 |

Diukur dengan Rasio Hamming polos (tanpa bobot, supaya penggarisnya tidak ikut berubah),
pemisahan membaik dari 0,5698 menjadi 0,5230; kemurnian `Level` di dalam klaster naik dari
93,8 % ke 99,1 %.

---

## 4. Korpus TF-IDF: kenapa hanya nama menu

`prepare_foods()` di `src/recommender.py`.

Versi sebelumnya merangkai nama + keempat makro + label klaster + kategori. Tiga masalahnya
terukur.

1. **Angka jadi token, bukan besaran.** TF-IDF memperlakukan "280.0" sebagai kategori tersendiri,
   sehingga 280,0 dan 281,0 kkal sama sekali tidak berhubungan sementara dua menu yang kebetulan
   sama-sama 280,0 dianggap mirip. Dari 1.110 token kosakata, 376 (34 %) berupa angka — dan
   **nol** di antaranya pernah muncul di kueri pengguna.
2. **Token yang dimiliki semua dokumen ber-IDF nol.** Kata "calories", "protein", "fat",
   "carbohydrate", dan "cluster" ada di setiap baris, jadi tidak pernah membedakan apa pun.
3. **Kategori di dalam teks adalah kebocoran label.** `Food_Category` ikut ditulis, padahal ia
   juga yang dipakai menilai relevansi saat pengujian. Evaluasi apa adanya memberi
   MAP@5 = 1,0000 — angka yang sebenarnya mengukur pencocokan sebuah kata dengan dirinya sendiri.

| Representasi CBF_Text | Kosakata | MAP@5 | NDCG@5 |
|-----------------------|----------|-------|--------|
| nama + makro + klaster (lama) | 1.101 | 0,8887 | 0,9191 |
| **nama menu saja (dipakai)** | **722** | **0,8909** | **0,9206** |

Selisihnya tipis, dan justru itu temuannya: seluruh rangkaian makro dan label klaster tidak
menyumbang apa pun pada peringkat, padahal membengkakkan kosakata dari 722 ke 1.101 token.

### Catatan tentang kunci jawaban pengujian

Relevansi dinilai dengan `food_category_mask()` — fungsi yang sama yang dipakai `_rank_foods()` —
**bukan** dengan kolom `Food_Category`. `Food_Category` adalah keluaran `primary_food_category()`,
yang memberi satu label per menu dengan aturan "kategori pertama yang cocok yang menang" supaya
chip di kartu menu tidak berganda. Sebagai kunci jawaban ia terlalu sempit: "Keripik tempe"
berlabel Tahu/Tempe (urutan ke-6) dan bukan Kerupuk (ke-13), sehingga kueri "Kerupuk & Keripik" —
yang lima besarnya seluruhnya memang keripik — dihitung salah lima-limanya dan ber-AP@5 0,0000.
Ada 65 menu yang lolos mask tetapi berlabel utama lain.

Memakai definisi milik aplikasi sendiri menaikkan MAP@5 dari 0,6856 ke 0,8280 tanpa mengubah satu
baris pun kode perekomendasi. Setelah pola kategori dilengkapi, angkanya 0,8909.

---

## 5. Korpus TF-IDF latihan: kenapa hanya judul dan deskripsi

`prepare_exercises()` di `src/recommender.py`.

`Type`, `BodyPart`, `Equipment`, dan `Level` dikeluarkan karena dua alasan terukur.

1. **Keduanya sudah jadi penyaring.** Saat CBF memeringkat, kolamnya sudah disaring per target
   otot, per level, dan per jenis latihan. Token yang dimiliki hampir semua baris di dalam kolam
   itu ber-IDF nol.
2. **Atribut terstruktur bertabrakan dengan prosa.** Nilai kategorikal pecah jadi token dan
   bercampur dengan kata di deskripsi. Token "body" dari alat "Body Only" muncul di 877 baris,
   tetapi 473 (54 %) di antaranya **tidak** beralat Body Only — ia berasal dari kalimat seperti
   "lower your body".

Label klaster juga dikeluarkan: K-Modes dipakai sebagai pengurut keragaman lewat kolom
`Exercise_Cluster`, bukan sebagai kata.

---

## 6. Urutan empat kunci perangkingan menu

`_rank_foods()` di `src/recommender.py`. Urutannya `_category` → `_match` → `_nutrition` → `_score`.

**Kenapa gizi di atas CBF.** Dulu `_score` yang di atas, dan itu keliru untuk kasus yang paling
sering terjadi: pengguna memilih kategori tanpa mengetik apa pun. Saat itu seluruh menu di
kategori itu memenuhi permintaannya sama baiknya, sehingga TF-IDF tidak punya preferensi untuk
diperingkat — yang tersisa hanyalah artefak. Terukur: korelasi skor TF-IDF dengan jumlah kata di
nama menu mencapai **−0,966** pada kategori "Ayam", dan di bawah −0,5 pada 5 dari 14 kategori.
Makin sedikit kata lain yang mengencerkan token kategori, makin tinggi skornya — jadi `bubur ayam`
(0,671) menang atas `sate ayam` (0,616) semata karena namanya lebih pendek.

**Kenapa perlu pagar keragaman.** Menaikkan gizi saja merusak menunya: `nutrition_fit_score`
adalah skor tetap per menu, jadi sebagai kunci utama di dalam kolam yang sudah sempit, pemenangnya
selalu itu-itu juga.

| Ukuran | Susunan lama | Gizi saja | Gizi + pagar (dipakai) |
|--------|--------------|-----------|------------------------|
| Protein rata-rata menu | 82,9 g | 102,4 g | 99,8 g |
| Kerapatan kkal/100 g | 204,7 | 199,4 | 197,3 |
| Menu monoton (≥3 sejenis) | 0 | 7 | 0 |
| MAP@5 kesesuaian gizi | 0,1951 | 0,4827 | 0,4795 |

Diukur atas 75 menu harian (5 profil × 15 kategori). Pasien penurunan berat badan yang meminta
"Ayam" menerima 4 ayam goreng dari 8 item sebelum pagar dipasang.

---

## 7. Template menu per tujuan

`MEAL_TEMPLATES` di `src/recommender.py`.

Sebelumnya hanya ada **satu** template untuk ketiga tujuan, sehingga pengguna yang wajib
menurunkan berat menerima menu yang sama persis dengan yang ingin menaikkan berat — 7 dari 8 item
identik, hanya gramasinya berbeda. Tujuan menggerakkan target kalori, tetapi tidak menggerakkan
**pilihan** menunya.

| Tujuan | Sarapan | Makan Siang | Camilan | Makan Malam |
|--------|---------|-------------|---------|-------------|
| Lose Weight | B + C | A + B + C | C | B + C |
| Maintain Weight | A + B | A + B + C | C | B + C |
| Gain Weight | A + B | A + B + D | A | A + C |

Setiap tujuan tetap berisi 8 item supaya ukuran porsinya sebanding: menambah item berarti membagi
kuota slot ke lebih banyak bagian, dan porsinya mengecil. Peran D hanya muncul pada tujuan
menaikkan berat — ia padat kalori (425 kkal, 62 % dari lemak), berguna untuk menambah berat tetapi
justru yang paling perlu dihindari saat menurunkannya. Camilan selalu satu item pada ketiga
tujuan; dua item membuat "camilan" terbaca seperti waktu makan keempat.

---

## 8. Pagar bentuk sajian slot makan berat

`MAIN_MEAL_UNSUITABLE_PATTERN` dan `DESSERT_PATTERN` di `src/recommender.py`.

Dilaporkan dari pemakaian nyata: **"kue dadar gulung" muncul sebagai menu Makan Siang**. Ia jajanan
pasar — angka gizinya boleh saja cocok untuk slot itu, tetapi bentuk sajiannya bukan komponen makan
berat.

Dari 173 menu yang pernah mengisi slot utama, 12 di antaranya berbentuk kudapan manis dengan
28 kemunculan, dan **10 dari 12 lolos** dari pola sarapan yang sudah ada.

| Ukuran | Sebelum | Sesudah |
|--------|---------|---------|
| Kudapan di slot makan berat | 28 | **0** |
| Menu harian tidak penuh 8 item | 0 | **0** |
| Kandidat slot utama | 780 | 625 |
| Kandidat slot camilan | 275 | 275 |
| Kepatuhan preferensi | 85,2 % | 81,7 % |
| Kerapatan energi menu | 216,3 kkal/100 g | **197,3 kkal/100 g** |

Kepatuhan turun karena kerupuk kini tidak boleh mengisi slot utama sama sekali. Itu bayaran yang
disengaja, dan imbalannya kerapatan energi menu ikut turun.

`SNACK_ALWAYS_PATTERN` ikut digabung ke pagar ini karena isinya — kerupuk, keripik, rempeyek,
getuk, intip — memang selalu berstatus camilan: kalau ia tidak pernah boleh keluar dari slot
camilan, ia juga tidak boleh masuk slot makan berat.

### Kategori "Telur" dan kata "dadar"

Pola kategori Telur dulu memuat kata `dadar`. Keempat hidangan telur dadar di dataset
(`telur dadar`, `Telur Ayam dadar`, `Telur Bebek dadar`, `telur itik dadar`) **seluruhnya sudah
memuat kata "telur"**, jadi kata itu tidak menambah jangkauan apa pun — yang ia tambahkan justru
salah: "kue dadar" dan "kue dadar gulung".

---

## 9. Peran klaster pengguna: segmentasi, bukan personalisasi

`clean_members()` di `src/recommender.py`.

Kolom `User_Cluster` adalah keluaran **segmentasi**: ia menunjukkan anggota terbagi menjadi
kelompok yang sejalan dengan mandat IMT, dan ditampilkan sebagai label segmen. Ia **tidak** dipakai
menyusun rekomendasi menu maupun latihan, dan itu keputusan yang diambil setelah diuji.

1. **Klaster tidak membawa informasi baru.** Ia dibentuk dari delapan atribut yang semuanya sudah
   dipakai langsung oleh rekomendasi — tujuan menggerakkan `MEAL_TEMPLATES` dan
   `EXERCISE_TYPE_PLAN`, level menggerakkan prioritas alat dan set/repetisi, berat/tinggi/umur/
   gender menggerakkan target kalori. Mengopernya berarti mengirim informasi yang sama dua kali,
   dalam bentuk lebih kasar: 5 kategori menggantikan 8 atribut.
2. **Anggota satu klaster tidak seragam pada yang menentukan porsi.** Setelah `Fitness_Goal`
   dibobot, klaster menyatu pada **tujuan** (kemurnian 99,3 %), bukan pada tubuh. Di klaster 5
   misalnya, umur merentang 18–59 tahun dan IMT 18,5–49,8, sehingga target kalori anggotanya
   berselisih sampai **2.013 kkal/hari**.

Yang dikandung klaster tetap sampai ke rekomendasi lewat `Fitness_Goal`, yang sekaligus atribut
pembentuk klaster **dan** masukan langsung rekomendasi.

---

## 10. Program latihan: jenis dan alat tidak dipilih pengguna

`EXERCISE_TYPE_PLAN` dan `EQUIPMENT_PRIORITY` di `src/recommender.py`.

**Jenis latihan.** Sebelumnya `Jenis Latihan` adalah input formulir dengan nilai bawaan "Strength",
dan tujuan kebugaran hanya dipakai di baris terakhir untuk menempelkan set/repetisi. Akibatnya
kelima latihan yang direkomendasikan **identik** untuk ketiga tujuan — pengguna obesitas menerima
5 latihan beban dan nol kardio.

Input itu juga memberi ilusi kendali: pada target Dada, 142 dari 149 latihan (95 %) berlabel
Strength, jadi memilih "Strength" hampir tidak menyaring apa pun. Yang benar-benar dibuangnya
justru Cardio dan Plyometrics — pada target Kaki, 14 Cardio dan 36 Plyometrics — yang paling
dibutuhkan pengguna yang wajib menurunkan berat.

Dasarnya nilai MET: Plyometrics 8,0 dan Cardio 7,0 membakar sekitar 1,6× lipat Strength 5,0.

**Alat.** Input `Alat` yang lama tidak sekadar tidak berguna — ia **dilawan** oleh kodenya sendiri.
Pengendali keberagaman memaksa tiga peringkat teratas beralat berbeda, sehingga dari 36 slot yang
diuji hanya 10 yang memakai alat yang dipilih pengguna. Setiap pilihan alat menghasilkan tepat
1 dari 3.

Urutan prioritas disusun menurut keamanan dan kesesuaian level: mesin didahulukan untuk pemula
karena jalur gerakannya terpandu; barbel bebas didahulukan untuk expert karena menuntut kendali
yang belum dimiliki pemula.

---

## 11. Tangga pelonggaran level

`EXERCISE_LEVEL_LADDER` dan `NEEDS_SUPERVISION_COLUMN` di `src/recommender.py`.

Menambal kelangkaan nyata di dataset: **1.244 dari 1.359 latihan (91,5 %) berlabel Intermediate**
dan hanya 105 berlabel Beginner, sehingga pengguna pemula cuma melihat 7,7 % data. Pada target Bahu
bahkan hanya ada **satu** latihan berlabel Beginner dari 191 — dan jenisnya Stretching, yang tidak
masuk komposisi program. Sistem lama memang mengembalikan 1 latihan saja untuk kombinasi itu.

Lapis pertama adalah level pengguna sendiri; bila kolamnya kurang, naik satu lapis dan latihan
tambahan itu **ditandai**, bukan disamarkan.

Hasil uji 63 kombinasi (7 otot × 3 tujuan × 3 level): 63 dari 63 terisi penuh, 21 dari 315 slot
(6,7 %) perlu pendampingan, seluruhnya terpusat pada pengguna level Beginner.

---

## 12. Jumlah latihan bawaan

`DEFAULT_EXERCISE_COUNT` di `src/recommender.py`.

Angka ini hanya **nilai awal**; pengguna tetap boleh menggesernya. Waktu yang tersedia hari ini
adalah konteks yang tidak dimiliki sistem — aplikasi tidak pernah menanyakan durasi sesi, dan
`activity_level` menjawab "seberapa sering berolahraga", bukan "berapa lama waktu Anda sekarang".

Pemula sengaja diberi angka terkecil, dan itu bukan sekadar soal beban latihan: meminta lebih
sedikit mengurangi seberapa sering tangga pelonggaran level terpaksa dipakai.

Rentangnya dijaga 3–6, bukan 3–8 penuh. Set dan repetisi sudah bervariasi lewat
`TRAINING_PARAMETERS`, jadi kalau jumlahnya ikut menyebar penuh kedua sumber variasi berkalian:
total repetisi akan merentang 90–640 (7,1×). Pada 3–6 rentangnya 90–480 (5,3×), masih sepadan
dengan jarak antara pemula beraktivitas sedang dan expert yang sangat aktif.

---

## 13. Pagar tujuan kebugaran berbasis IMT

`GOAL_GUARDRAILS` di `src/nutrition.py`.

**Kenapa obesitas tidak diberi pilihan sama sekali.** Menjaga berat dan menaikkan berat sama-sama
tidak menurunkan berat badan. Memblokir salah satunya sambil mengizinkan yang lain berarti melarang
pilihan yang justru lebih ringan akibatnya — pada 98 kg / 172 cm, "menjaga" memberi target
2.626 kkal sedangkan "menaikkan" memberi 2.926 kkal. Keduanya diblokir bersama supaya urutan
ketatnya tidak terbalik.

**Ambangnya ikut `classify_bmi()`, bukan ambang WHO global.** Aplikasi menampilkan kategori
Asia-Pasifik di layar ("Gemuk" mulai IMT 23), jadi pagarnya harus berdiri di atas ambang yang sama.
Kalau tidak, layar dan aturan bisa berbeda pendapat tentang orang yang sama.

Tingkat perlakuan, dari longgar ke ketat: `saran` → `boleh` → `syarat` → `warning` → `error` →
`tetap` → `blokir`.

### Kenapa berat dan tinggi berada di luar `st.form`

`calorie_view()` di `src/views/calorie.py`.

Streamlit menahan nilai widget di dalam form sampai tombol kirim ditekan. Selama keduanya berada
di dalam form, IMT belum diketahui saat pilihan Tujuan dirender — dan pengguna obesitas bisa
memilih "Menaikkan Berat" tanpa satu pun peringatan, lalu menerima target 2.926 kkal alih-alih
2.126 kkal. Selisih 800 kkal/hari itu setara 0,73 kg per minggu ke arah yang berlawanan dengan
kondisinya.

Di luar form, keduanya memicu rerun begitu nilainya dikunci, sehingga `goal_guardrail()` sudah
punya IMT sebelum menyusun pilihan tujuan. Rerun-nya murah karena `get_data()` di-cache.

---

## 14. Kelayakan menu: dari daftar izin ke daftar tolak

`filter_recommendable_foods()` di `src/recommender.py`.

Dulu kelayakan ditentukan **daftar izin**: sebuah menu hanya boleh direkomendasikan kalau namanya
memuat salah satu dari 46 kata masak ("nasi", "goreng", "rebus", …). Aturan itu membuang 1.187 dari
1.586 baris, dan 684 di antaranya bukan bahan mentah sama sekali — "abon", "bakwan", "bacang",
"buras", "buntil", "bika ambon", "bakpia", "barongko" hilang hanya karena penulisnya tidak
menyebut cara masak di nama menunya.

Sekarang dibalik menjadi **daftar tolak**: sebuah menu diterima kecuali namanya menunjukkan ia
bukan hidangan siap santap. Arah kesalahannya ikut berbalik — dulu risikonya membuang makanan jadi,
sekarang risikonya meloloskan bahan — jadi daftarnya disusun dari pemeriksaan seluruh isi dataset.

| Alasan penolakan | Baris | Contoh |
|------------------|-------|--------|
| Bahan, bumbu, olahan setengah jadi | 488 | Akar tonjong segar, Ampas tahu mentah |
| Gizi tidak masuk akal | 101 | Agar-agar, Bawang goreng |
| Protein diawetkan garam | 59 | Dendeng, ikan asin, telur asin |
| Bukan satu hidangan utuh | 58 | Andewi, Asam masak di pohon, Baligo |
| Bukan pangan manusia | 30 | Ampas kacang hijau, Ampas Tahu |
| Dikecualikan lewat daftar khusus | 20 | Es Sirup, Lemonade, Melase |
| Non-halal atau satwa dilindungi | 9 | Ham, Ikan Belida |
| Buah dipakai sebagai bahan | 7 | Jantung Pisang segar, Bonggol pisang |

Satu baris bisa kena lebih dari satu alasan. Yang lolos seluruh saringan: **780 menu**.

### Kata "segar" punya dua arti

`RAW_FRESH_PATTERN` dan `FRESH_FRUIT_PATTERN`.

- "Sapi daging gemuk segar", "Udang galah segar" → bahan mentah, wajib dimasak dulu.
- "Mangga segar", "Pisang kepok segar" → justru bentuk siap santapnya, dan camilan paling sehat
  yang bisa ditawarkan aplikasi gizi.

Bug yang diperbaiki: sebelumnya "segar" ada di dalam `INGREDIENT_PATTERN`, sehingga **30 buah segar
terbuang diam-diam**. Cacatnya tidak terlihat selama pengujian memakai `data/food_nutrition.csv`,
karena berkas itu memuat nama yang sudah dipendekkan ("Mangga"), sedangkan tabel database menyimpan
nama asli TKPI ("Mangga segar").

### Penyisiran adversarial

Daftar `NOT_A_MEAL_PATTERN` disusun dari penyisiran seluruh 866 nama menu oleh 12 peninjau, lalu
setiap tuduhan diadu dengan pembantah yang tugasnya **membantah**. Dari 65 tuduhan, 51 gugur dan 14
bertahan. Yang gugur termasuk Kluwek, Petis, Taoco, Peterseli, Coklat bubuk, dan Gelatine, karena
semuanya ternyata dipakai sebagai komponen hidangan Indonesia yang sah — tanpa lapis pembantah,
keenamnya akan ikut terhapus.

---

## 15. Ketersediaan gambar tidak menentukan kelayakan menu

`filter_recommendable_foods()` dan `image_status_from_cache()` di `src/recommender.py`.

Dulu menu yang gambarnya tidak bisa dimuat langsung dibuang. Tiga masalahnya:

1. Menu hilang karena alasan yang tidak ada hubungannya dengan gizi. Tautan CDN pihak ketiga lapuk;
   63 dari 260 menu sudah kehilangan gambarnya.
2. Jumlah menu jadi tidak bisa direproduksi — pemeriksaannya lewat jaringan, jadi hasilnya
   bergantung pada koneksi dan pembatasan laju host saat itu.
3. Pemuatan pertama di mesin baru makan ~33 detik hanya untuk memeriksa 260 URL.

Sekarang menu tanpa gambar tetap direkomendasikan dan kartunya memakai gambar pengganti. Status
gambar dibaca dari **cache saja**, tanpa satu pun permintaan jaringan saat start. URL yang belum
pernah diperiksa dianggap bisa ditampilkan (optimistis).

### Gambar dibaca dari dataset aktif, bukan dari salinan rekomendasi

`gambar_terkini()` di `src/views/meal.py`.

Rekomendasi tersimpan adalah salinan utuh baris menu saat menu disusun, termasuk `image` dan
`Has_Image`. Salinan itu harus diabadikan untuk angka gizi dan gramasi — riwayat pengguna tidak
boleh berubah surut. Tetapi gambar bukan bagian dari rekomendasi; ia data tampilan.

Terukur: sembilan kartu "Mie Goreng" tersimpan dengan tautan kbu-cdn yang sudah mati dan
`Has_Image` bernilai False, sehingga kartunya menampilkan kotak kosong, padahal tabel
`food_nutrition` sudah memuat tautan pengganti yang sehat.

---

## 16. Penanda versi dataset

`DATASET_VERSION_PATH` di `src/core/data.py`.

`st.cache_data` menyimpan hasil di memori **proses** yang berjalan, sedangkan panel admin dan
aplikasi pengguna adalah dua proses `streamlit run` terpisah di port berbeda. Memanggil `.clear()`
sesudah admin menyimpan karena itu hanya mengosongkan cache milik panel admin.

Akibat nyatanya terukur: mengganti URL gambar "Mie Goreng" lewat panel admin benar-benar tersimpan
ke tabel `food_nutrition`, tetapi aplikasi pengguna tetap menampilkan tautan lama sampai prosesnya
dijalankan ulang.

Obatnya: penanda versi disimpan sebagai berkas kecil di `data/`, dan isinya dipakai sebagai bagian
dari **kunci cache**. Begitu admin menyimpan, penandanya berubah, sehingga pemanggilan berikutnya
di proses mana pun otomatis meleset dari cache.

**Kenapa berkas, bukan kolom di database.** Pemeriksaannya terjadi di setiap rerun Streamlit — tiap
centang, tiap tombol — sehingga harus nyaris gratis. Membaca berkas sekecil ini memakan **0,24 ms**,
sedangkan satu kueri ke Supabase memakan ratusan milidetik. Cara ini menuntut kedua aplikasi
berjalan di mesin yang sama, dan memang begitulah sistem ini dijalankan.

Pemuatan penuh dataset memakan **27,6 detik** (13,0 s baca database + 12,4 s K-Prototypes +
0,5 s K-Means + 1,7 s K-Modes), sehingga memasang `ttl` pendek pada cache bukan pilihan yang layak.

---

## 17. Ketahanan koneksi database

`ulangi_bila_koneksi_putus()` dan `_connection_is_alive()` di `src/database.py`.

Penanda `closed` pada objek koneksi hanya diketahui **sisi klien**. Bila server yang memutus —
misalnya Supavisor menutup koneksi yang menganggur — klien tetap mengira koneksinya hidup sampai
query berikutnya gagal. Karena itu koneksi yang sudah menganggur melewati ambang tertentu diuji
dengan `SELECT 1` sebelum dipakai.

`append_record()` **sengaja tidak** dipasangi dekorator ulang-otomatis: ia menambah baris, dan
mengulangnya berisiko menggandakan data seandainya commit pertama sebenarnya sempat sampai.

**Supavisor membuang opsi startup libqp `-c`** (kecuali `search_path`), sehingga
`idle_in_transaction_session_timeout` terbaca kembali sebagai `0`. Timeout karena itu dipasang
dengan perintah `SET` yang dijalankan lalu di-commit.

---

## 18. Keamanan kata sandi

`hash_password()` dan `verify_password()` di `src/core/state.py`.

Kata sandi disimpan sebagai hash **Argon2id** dengan garam acak. Akun lama ber-hash SHA-256 masih
bisa login, lalu otomatis dimigrasi ke Argon2id dan hash lamanya dihapus — migrasi dilakukan pada
titik login karena hanya di situlah aplikasi memegang kata sandi asli. Kata sandi polos ditolak.

Status verifikasi surel dicek **setelah** kata sandi terbukti benar. Kalau dicek duluan, orang bisa
menebak surel mana yang terdaftar cuma dengan kata sandi asal — pesan "belum diverifikasi" sudah
membocorkan bahwa akunnya ada.

---

## 19. Isolasi pengujian

`tests/_isolasi.py`.

Penyimpanan aplikasi cuma satu (Supabase), jadi skrip uji tidak punya penampung sementara di luar
database. Isolasinya dilakukan di tingkat **schema Postgres**: `pakai_schema_uji()` mengisi env
`POSTGRES_SCHEMA` dengan schema sekali-pakai, membuangnya lebih dulu supaya mulai dari nol, lalu
membuangnya lagi lewat `atexit`.

`search_path` koneksi uji sengaja **tidak** menyertakan `public`: kalau ada tabel yang belum
terbentuk, query-nya gagal terang-terangan alih-alih diam-diam membaca data asli.

Skrip uji **tidak boleh** dijalankan berbarengan dengan notebook pengujian: keduanya memakai nama
schema sekali-pakai yang sama.
