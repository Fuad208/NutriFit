# Prioritas Revisi NutriFit

Dokumen ini dibuat setelah menelusuri behavior kode pada `app.py`, `src/recommender.py`, `src/nutrition.py`, dan sampel dataset `data/food_nutrition.csv` serta `data/training_program.csv`.

sampel data baru: https://www.kaggle.com/datasets/dwiiyy/nutricheck-image-dataset?resource=download

## Ringkasan Behavior Saat Ini

- Rekomendasi makanan awal sudah memakai TF-IDF dan cosine similarity terhadap `CBF_Text`, tetapi kandidat makanan diambil langsung dari dataset komposisi pangan. Dataset ini berisi banyak bahan mentah/bahan pangan, misalnya `Akar tonjong segar`, `Ampas tahu mentah`, dan `Anak sapi daging ... segar`, sehingga output bisa terasa bukan menu umum.
- Lunch saat ini sengaja menghasilkan 4 item karena `MEAL_TEMPLATE["Lunch"] = ["A", "B", "B", "C"]`.
- Pencegahan duplikat makanan hanya berlaku di dalam satu slot makan karena `used_ids` dibuat ulang pada setiap meal slot. Akibatnya makanan yang sudah muncul di sarapan masih bisa muncul lagi di makan siang/makan malam.
- Swap makanan tidak menghitung ulang TF-IDF/cosine. Saat ini hanya memakai `name.str.contains(preference)` sebagai skor, sehingga akurasinya beda dari rekomendasi awal dan duplikat lintas slot masih mungkin terjadi.
- Aktivitas terakhir di dashboard masih hardcoded `2 jam lalu`, `4 jam lalu`, dan `6 jam lalu`, bukan dari `created_at` transaksi.
- Target otot latihan saat ini memakai semua `BodyPart` dari dataset, total 17 kategori: Abdominals, Abductors, Adductors, Biceps, Calves, Chest, Forearms, Glutes, Hamstrings, Lats, Lower Back, Middle Back, Neck, Quadriceps, Shoulders, Traps, Triceps.
- Rekomendasi latihan difilter berdasarkan `BodyPart`, `Type`, dan level, lalu diranking TF-IDF/cosine. Jika hasil filter kosong, kode fallback ke semua latihan sesuai level, sehingga target otot yang diminta bisa tidak terjaga.
- Tutorial latihan dicari dengan fuzzy matching terhadap `dataProgramTraining/data/exercises.json`. Jika tidak ketemu, aplikasi tetap menampilkan latihan dan hanya memberi info bahwa tutorial belum ditemukan.
- Tombol swap latihan sebenarnya ada di kode sebagai `Switch Training`, tetapi perlu dicek UI/flow karena pengguna melaporkan tidak tampil/tidak jalan.
- K-prototypes untuk profil pengguna dihitung ulang di `assign_user_cluster()` setiap submit form "Hitung Kalori". Ini tidak sesuai narasi laporan jika fase online seharusnya hanya mengalokasikan user ke centroid tetap.
- IMT masih memakai klasifikasi umum: Underweight `<18.5`, Normal `<25`, Overweight `<30`, Obese `>=30`, bukan klasifikasi Asia-Pasifik pada laporan.
- Penyesuaian kalori masih `Lose Weight = -400` dan `Gain Weight = +350`, sedangkan laporan meminta defisit 500 dan surplus 300 kkal.
- Protein masih dihitung flat 25% dari target kalori, belum memakai 1,6-2,2 g/kg BB berdasarkan tujuan.

## Skala Prioritas

| Prioritas | Point | Status | Revisi | Kesulitan | Alasan |
|---|---|---|---|---:|---|
| P1 | Point 1 | Done | Menu harus umum, bukan bahan mentah, dan gambar valid | Sulit | Ini bukan hanya bug kode. Dataset makanan saat ini berisi bahan pangan mentah dan item langka. Perlu strategi kurasi: tambah kolom kategori/status siap makan, blacklist keyword mentah/segar/bahan, whitelist menu umum, validasi URL gambar, atau ganti dataset menu. |
| P1 | Point 2 | Done | Duplikat makanan lintas slot | Mudah | Akar masalah jelas: `used_ids` di-reset per slot. Pindahkan `used_ids` menjadi global untuk seluruh hari. |
| P1 | Point 3 | Done | Rekomendasi makan siang cukup 3 menu | Mudah | Ubah `MEAL_TEMPLATE["Lunch"]` dari 4 cluster menjadi 3 cluster dan pastikan target kalori per item otomatis menyesuaikan. |
| P1 | Point 4 | Done | Swap makanan hitung ulang TF-IDF/cosine dan cegah duplikat | Sedang | Perlu samakan scoring swap dengan rekomendasi awal memakai `CBF_Text`, serta kirim daftar semua makanan yang sedang tampil dan daftar excluded ke `swap_food()`. |
| P2 | Point 5 | Done | Jam aktivitas terakhir tidak valid | Mudah-Sedang | Dashboard masih hardcoded. Perlu ambil record terbaru dari calorie/meal/workout, hitung relative time dari `created_at`, dan tampilkan waktu aktual. Jika memakai timezone lokal, perlu konsisten dengan penyimpanan timestamp. |
| P2 | Point 6 | Done | Target otot diperkecil jadi 7 otot utama | Sedang | UI mudah, tapi mapping datanya perlu hati-hati: dada -> Chest, bahu -> Shoulders/Traps, punggung -> Middle Back/Lower Back, lengan -> Biceps/Triceps/Forearms, core/inti/perut -> Abdominals, kaki -> Quadriceps/Hamstrings/Glutes/Calves/Abductors/Adductors, sayap -> Lats. |
| P1 | Point 7 | Done | Latihan harus sesuai target otot | Sedang | Perlu hilangkan fallback yang mengabaikan `BodyPart`, tambah mapping 7 otot utama ke beberapa `BodyPart` dataset, dan pastikan ranking tidak memilih di luar target. |
| P1 | Point 8 | Done | Latihan tanpa tutorial/video terutama beginner dihapus | Sedang-Sulit | Perlu preprocessing yang menghubungkan dataset latihan utama dengan tutorial. Karena matching saat ini fuzzy dan tidak 1:1, perlu membuat indeks tutorial yang cukup akurat lalu filter rekomendasi beginner hanya pada latihan yang punya media/tutorial. |
| P2 | Point 9 | Done | Swap latihan tidak jalan/tidak tampil | Sedang | Fungsi dan tombol ada, jadi perlu reproduksi UI. Kemungkinan penyebab: posisi tombol kurang terlihat, key tidak stabil, filter aktif berbeda dari session, atau kandidat kosong karena semua title masuk excluded/current. |
| P0 | Point 10 | Done | K-prototypes jangan training ulang saat fase online | Sulit | Ini menyangkut validitas metode di laporan. Perlu menyimpan artefak training offline: scaler, centroid numerik, mode kategorikal, dan metadata kolom/cluster, lalu `assign_user_cluster()` hanya menghitung jarak ke centroid tetap. Perlu migrasi kecil alur data dan validasi performa. |
| P0 | Point 11 | Done | Klasifikasi IMT Asia-Pasifik sesuai laporan | Mudah | Dampak langsung ke hasil kesehatan dan mudah diubah di `src/nutrition.py`. Label UI juga perlu disesuaikan agar `Gemuk`, `Obesitas I`, `Obesitas II` tampil benar. |
| P0 | Point 12 | Done | Defisit 500 / surplus 300 kkal | Mudah | Mudah diubah di `GOAL_CALORIE_ADJUSTMENTS`, dan sangat penting karena memengaruhi seluruh target nutrisi dan rekomendasi menu. |
| P0 | Point 13 | Done | Protein 1,6-2,2 g/kg BB berdasarkan tujuan | Sedang | Perlu ubah formula agar protein berbasis berat badan dan tujuan, lalu kalori sisa dibagi ke karbohidrat/lemak. Perlu keputusan mapping, misalnya defisit 2,2 g/kg, maintain 1,8 g/kg, surplus 1,6-2,0 g/kg. Catatan: teks revisi nomor 13 terpotong pada bagian "dan gak", jadi detail akhirnya perlu dikonfirmasi. |

## Urutan Pengerjaan Disarankan

1. Rapikan formula numerik yang langsung memengaruhi output: IMT Asia-Pasifik, defisit/surplus kalori, protein g/kg BB.
2. Betulkan logika rekomendasi makanan yang cepat berdampak: lunch 3 item, used ID global, dan swap memakai TF-IDF/cosine + anti-duplikat.
3. Kurasi kualitas dataset/menu makanan: minimal blacklist bahan mentah dan validasi gambar; idealnya pisahkan dataset bahan pangan dari dataset menu siap makan.
4. Perbaiki target otot latihan: batasi UI ke 7 otot utama, buat mapping ke `BodyPart` dataset, dan jangan fallback ke body part lain tanpa pemberitahuan.
5. Filter latihan beginner agar hanya yang punya tutorial/media, lalu perbaiki tampilan dan flow swap latihan.
6. Ubah k-prototypes menjadi pipeline offline/online sesuai laporan. Ini sebaiknya dikerjakan setelah output utama stabil karena menyentuh desain model.
7. Ganti aktivitas terakhir dari teks hardcoded ke data transaksi terbaru.

## Catatan Risiko

- Revisi makanan nomor 1 berpotensi paling memakan waktu karena kualitas output sangat tergantung kualitas dataset, bukan hanya algoritma.
- Revisi k-prototypes perlu keputusan lokasi penyimpanan artefak model. Opsi sederhana: file JSON/pickle di folder model lokal; opsi lebih rapi: tabel khusus centroid/mode di database.
- Revisi target otot harus diselaraskan dengan istilah laporan. Di dataset, "sayap" paling dekat dengan `Lats`, sedangkan "punggung" bisa mencakup `Middle Back` dan `Lower Back`.
- Jika laporan mensyaratkan persis 7 target otot, admin dataset tetap boleh menyimpan 17 body part, tetapi UI dan rekomendasi pengguna sebaiknya memakai mapping 7 otot utama.

## Sumber Data Kandidat Untuk Point 1

Masalah Point 1 muncul karena dataset saat ini lebih mirip tabel komposisi pangan/bahan mentah, bukan katalog menu siap makan. Untuk mengganti atau memperkaya dataset, kandidat paling cocok adalah:

| Prioritas | Sumber | Kegunaan | Kelebihan | Catatan |
|---|---|---|---|---|
| Utama untuk variasi | [Food.com - Recipes and Reviews - Kaggle](https://www.kaggle.com/datasets/irkaal/foodcom-recipes-and-reviews/data) | Dataset resep siap makan skala besar dengan nutrisi dan gambar | Lebih dari 500.000 resep, 312 kategori, berisi cooking time, servings, ingredients, nutrition, instructions, dan image URL | Paling cocok kalau targetnya variasi menu banyak. Perlu mapping kolom nutrisi ke `calories`, `proteins`, `fat`, `carbohydrate`, dan filter menu yang familiar untuk user Indonesia. |
| Utama untuk nutrisi+gambar | [Recipe Images with Nutritional Information - Kaggle](https://www.kaggle.com/datasets/crispen5gar/recipe-images-with-nutritional-information) | Dataset recipe image dengan makro nutrisi | Punya CSV `data.csv` dengan `image`, `carbs`, `fat`, `kcal`, `protein`, dan folder gambar | Lebih siap masuk schema aplikasi karena sudah ada gambar dan makro. Cek jumlah menu dan variasi kelas sebelum dijadikan dataset utama. |
| Referensi besar multimodal | [Recipe1M+ / im2recipe - MIT](https://pic2recipe.csail.mit.edu/) | Dataset resep besar dengan gambar, bahan, dan instruksi | Cocok untuk riset multimodal dan variasi resep sangat besar | Akses dataset biasanya perlu form/approval dan ukuran sangat besar, jadi kurang praktis untuk aplikasi skripsi/proyek kecil. |
| Referensi besar terbaru | [UniFood](https://pengkun-jiao.github.io/UniFood-project/) | Dataset food-nutrition analysis skala besar | 501.533 gambar makanan dengan kategori, ingredients, cooking instructions, dan nutrisi image-level/ingredient-level | Sangat lengkap secara konsep, tapi perlu cek akses file, lisensi, dan effort integrasi. |
| Seed Indonesia | [Nutricheck Dataset - Kaggle](https://www.kaggle.com/datasets/dwiiyy/nutricheck-image-dataset) | Dataset menu Indonesia dengan gambar dan CSV nutrisi | Fokus ke makanan yang umum dikonsumsi di Indonesia, punya gambar, dan nutrition CSV dari FatSecret | Hanya 53 kelas, jadi jangan dijadikan sumber tunggal kalau butuh variasi luas. Cocok sebagai seed menu Indonesia atau validasi lokal. |
| Pendamping nutrisi | [Nutritional Analysis and Macro-Micro Nutrient Profiling of Indonesian Culinary Recipes - Mendeley](https://data.mendeley.com/datasets/8b4ztns76h) | Nutrisi resep khas Indonesia | Memuat resep Indonesia, porsi, langkah masak, dan perhitungan makro/mikro | Sangat bagus untuk validasi nutrisi menu, tapi perlu dicek apakah menyediakan gambar. |
| Pendamping gambar | [Indonesian Food Image - Mendeley](https://data.mendeley.com/datasets/vtjd68bmwt/1) | Gambar makanan Indonesia umum | Kelasnya menu populer seperti bakso, gado-gado, gudeg, nasi goreng, pempek, rawon, rendang, sate, soto | Gambar saja, tidak cukup untuk nutrisi. Cocok digabung dengan data nutrisi/resep. |
| Pendamping gambar lokal | [Padang Cuisine - Kaggle](https://www.kaggle.com/datasets/faldoae/padangfood) | Gambar makanan Padang | Menambah variasi lauk Indonesia seperti rendang, ayam pop, dendeng balado, gulai tunjang, sate padang, telur balado, gulai nangka, sambal ijo, perkedel | Hanya gambar dan 9 kelas Padang, jadi cocok untuk enrich image/label lokal, bukan nutrisi utama. |
| Pendamping resep | [Indonesian Food Recipes - Kaggle/Baselight](https://baselight.app/u/kaggle/dataset/canggih_indonesian_food_recipes) | Resep Indonesia siap masak | Banyak resep: ayam, kambing, sapi, telur, tahu, ikan, tempe; punya title, ingredients, steps, URL | Tidak langsung punya kalori/protein/lemak/karbohidrat; perlu dihitung lewat API nutrisi atau mapping bahan. |
| Tetap sebagai referensi | [Indonesian Food and Drink Nutrition Dataset - Kaggle](https://www.kaggle.com/datasets/anasfikrihanif/indonesian-food-and-drink-nutrition-dataset) | Sumber nutrisi per 100 gram dari TKPI/Kemenkes | Lengkap untuk bahan pangan dan sudah dipakai aplikasi sekarang | Jangan dipakai mentah sebagai rekomendasi menu. Lebih cocok jadi lookup nutrisi bahan atau fallback setelah kurasi. |
| API opsional | [FatSecret Platform API](https://platform.fatsecret.com/platform-api) | Food/recipe API dengan nutrisi dan gambar | Database besar, mendukung banyak negara, menyediakan food search, resep, nutrisi, dan image pada paket tertentu | Butuh API key dan cek batas penyimpanan/lisensi. |
| API opsional | [Spoonacular API](https://www.postman.com/spoonacular-api/spoonacular-api/documentation/rqqne3j/spoonacular-api) | Recipe search + nutrition + image | Bisa search recipe dengan filter kalori, protein, fat, carbs, meal type, diet | Lebih kuat untuk menu internasional; coverage menu Indonesia perlu diuji. |
| API opsional | [Edamam Nutrition Analysis API](https://developer.edamam.com/edamam-docs-nutrition-api) | Analisis nutrisi dari teks resep | Mode food logging menyaring makanan siap konsumsi sehingga raw ingredients bisa dikurangi | Ketentuan caching/penyimpanan data ketat; cocok untuk enrichment runtime, bukan scraping massal. |

Rekomendasi praktis:

1. Jika prioritas utama adalah variasi menu, pakai Food.com sebagai base dataset karena jumlah resep dan kategorinya jauh lebih besar.
2. Jika ingin schema cepat masuk ke aplikasi, coba dulu Recipe Images with Nutritional Information karena sudah punya gambar dan makro nutrisi.
3. Pakai Nutricheck, Mendeley Indonesian Food Image, Padang Cuisine, dan Indonesian Food Recipes sebagai layer lokalisasi agar rekomendasi tetap terasa cocok untuk user Indonesia.
4. Simpan dataset lama TKPI sebagai referensi nutrisi bahan, tetapi beri kolom kurasi seperti `is_ready_to_eat`, `is_common_menu`, dan `source`.
5. Untuk menu Indonesia yang belum punya nutrisi, gunakan FatSecret/Edamam/Spoonacular sebagai enrichment legal via API, bukan scraping sembarang.
