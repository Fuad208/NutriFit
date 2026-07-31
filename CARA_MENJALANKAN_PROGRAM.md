# Cara Menjalankan Program NutriFit dari Awal

Dokumen ini menjelaskan langkah menjalankan aplikasi NutriFit dari komputer kosong sampai aplikasi siap dipakai, termasuk membuat database, deploy tabel, import data awal, dan menjalankan aplikasi Streamlit.

## 1. Prasyarat

Pastikan sudah terpasang:

- Python 3.10 atau lebih baru
- MySQL Server atau PostgreSQL
- Terminal atau command prompt
- Git, jika proyek diambil dari repository

Aplikasi ini memakai Streamlit dan membaca dataset utama dari database SQL. Jadi database SQL perlu aktif sebelum aplikasi dijalankan.

## 2. Masuk ke Folder Proyek

Buka terminal, lalu masuk ke folder proyek:

```bash
cd "RecommendFood&Training"
```

Jika folder proyek berada di lokasi lain, sesuaikan path `cd` dengan lokasi proyek di komputer Anda.

## 3. Buat Virtual Environment Python

Buat environment:

```bash
python3 -m venv .venv
```

Aktifkan environment:

```bash
source .venv/bin/activate
```

Untuk Windows:

```bash
.venv\Scripts\activate
```

Setelah aktif, biasanya terminal menampilkan prefix `(.venv)`.

## 4. Install Dependency

Install semua library dari `requirements.txt`:

```bash
pip install -r requirements.txt
```

Dependency utama yang dipakai:

- `streamlit`
- `pandas`
- `numpy`
- `scikit-learn`
- `altair`
- `pymysql` untuk MySQL
- `psycopg[binary]` untuk PostgreSQL

## 5. Siapkan File Environment

Jika belum ada file `.env`, salin dari contoh:

```bash
cp .env.example .env
```

Aplikasi mendukung MySQL dan PostgreSQL. Pilih salah satu.

## 6. Setup Database MySQL

Gunakan konfigurasi seperti ini di `.env`:

```env
MYSQL=true
POSTGRES=false

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=password_mysql_anda
MYSQL_DATABASE=nutrifit
```

Catatan:

- Ganti `password_mysql_anda` sesuai password MySQL lokal.
- Database `nutrifit` akan dibuat otomatis oleh program saat script import dijalankan, selama user MySQL punya izin `CREATE DATABASE`.

Jika ingin membuat database secara manual:

```bash
mysql -u root -p
```

Lalu jalankan:

```sql
CREATE DATABASE IF NOT EXISTS nutrifit
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;
```

Keluar dari MySQL:

```sql
EXIT;
```

## 7. Setup Database PostgreSQL

Jika memakai PostgreSQL, gunakan konfigurasi seperti ini di `.env`:

```env
MYSQL=false
POSTGRES=true

POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password_postgres_anda
POSTGRES_DATABASE=nutrifit
```

Buat database PostgreSQL secara manual:

```bash
createdb -U postgres nutrifit
```

Atau masuk ke `psql`:

```bash
psql -U postgres
```

Lalu jalankan:

```sql
CREATE DATABASE nutrifit;
```

Keluar dari PostgreSQL:

```sql
\q
```

## 8. Deploy Tabel Dataset ke Database

Jalankan script import CSV:

```bash
python3 schema_data/import_csv_to_db.py
```

Script ini akan membuat dan mengisi tabel:

- `food_nutrition` dari `data/food_nutrition.csv`
- `gym_members` dari `data/gym_members.csv`
- `training_program` dari `data/training_program.csv`

Secara default, isi tabel dataset akan dikosongkan dulu lalu diisi ulang dari CSV.

Jika ingin append atau update tanpa truncate:

```bash
python3 schema_data/import_csv_to_db.py --append
```

Output yang diharapkan kurang lebih:

```text
food_nutrition: inserted ... rows
gym_members: inserted ... rows
training_program: inserted ... rows
```

## 9. Deploy Tabel Aplikasi dan Import Data JSON

Jalankan:

```bash
python3 schema_data/import_json_to_db.py
```

Script ini akan membuat dan mengisi tabel aplikasi:

- `users` dari `database/user.json`
- `calorie_records` dari `database/calorie.json`
- `meal_recommendations` dari `database/meal_recommendation.json`
- `workout_recommendations` dari `database/workout_recommendation.json`

Jika ingin menghapus isi tabel aplikasi dulu lalu import ulang:

```bash
python3 schema_data/import_json_to_db.py --replace
```

Output yang diharapkan kurang lebih:

```text
users: upserted ... rows
calorie.json: upserted ... rows
meal_recommendation.json: upserted ... rows
workout_recommendation.json: upserted ... rows
```

## 10. Verifikasi Tabel Database

Untuk MySQL:

```bash
mysql -u root -p nutrifit
```

Lalu cek tabel:

```sql
SHOW TABLES;
SELECT COUNT(*) FROM food_nutrition;
SELECT COUNT(*) FROM gym_members;
SELECT COUNT(*) FROM training_program;
SELECT COUNT(*) FROM users;
```

Untuk PostgreSQL:

```bash
psql -U postgres -d nutrifit
```

Lalu cek tabel:

```sql
\dt
SELECT COUNT(*) FROM food_nutrition;
SELECT COUNT(*) FROM gym_members;
SELECT COUNT(*) FROM training_program;
SELECT COUNT(*) FROM users;
```

Pastikan tabel dataset tidak kosong. Jika `gym_members`, `food_nutrition`, atau `training_program` kosong, aplikasi akan gagal memuat rekomendasi.

## 11. Jalankan Aplikasi

Pastikan virtual environment aktif:

```bash
source .venv/bin/activate
```

Jalankan Streamlit:

```bash
streamlit run app.py
```

Biasanya aplikasi terbuka otomatis di browser. Jika tidak, buka URL berikut:

```text
http://localhost:8501
```

## 12. Login atau Register

Anda bisa membuat akun baru melalui halaman `Register`.

Data seed juga menyediakan akun admin:

```text
Email: admin@gmail.com
Password: admin
```

Akun admin dapat membuka halaman `Admin Data` untuk melihat data user, riwayat rekomendasi, performa model, dataset makanan, dan dataset latihan.

## 13. Alur Penggunaan Aplikasi

Setelah login:

1. Masukkan profil tubuh dan gaya hidup.
2. Sistem menghitung BMI, BMR, TDEE, kebutuhan kalori, protein, karbohidrat, dan lemak.
3. Pilih preferensi makanan.
4. Sistem menampilkan rekomendasi makanan.
5. Pilih filter latihan.
6. Sistem menampilkan rekomendasi workout.
7. Riwayat rekomendasi tersimpan ke database.

## 14. Struktur Data Penting

Dataset utama:

```text
data/gym_members.csv
data/food_nutrition.csv
data/training_program.csv
```

Data aplikasi awal:

```text
database/user.json
database/calorie.json
database/meal_recommendation.json
database/workout_recommendation.json
```

Asset detail latihan:

```text
dataProgramTraining/data/exercises.json
dataProgramTraining/images/
dataProgramTraining/videos/
```

## 15. Refresh Data Setelah Perubahan CSV atau JSON

Jika file CSV dataset diubah, jalankan ulang:

```bash
python3 schema_data/import_csv_to_db.py
```

Jika file JSON aplikasi diubah, jalankan ulang:

```bash
python3 schema_data/import_json_to_db.py --replace
```

Setelah itu restart aplikasi Streamlit:

```bash
streamlit run app.py
```

## 16. Troubleshooting

Jika muncul error:

```text
Set MYSQL=true or POSTGRES=true in .env
```

Artinya aplikasi belum diarahkan ke database SQL. Periksa `.env` dan pastikan salah satu aktif:

```env
MYSQL=true
POSTGRES=false
```

atau:

```env
MYSQL=false
POSTGRES=true
```

Jika muncul error:

```text
Dataset tables are not ready
```

Jalankan:

```bash
python3 schema_data/import_csv_to_db.py
```

Jika muncul error:

```text
Dataset table(s) empty
```

Artinya tabel sudah ada tetapi belum berisi data. Jalankan ulang import CSV:

```bash
python3 schema_data/import_csv_to_db.py
```

Jika koneksi MySQL gagal:

- Pastikan MySQL Server sedang berjalan.
- Pastikan `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, dan `MYSQL_DATABASE` benar.
- Pastikan user MySQL punya izin membuat database dan tabel.

Jika koneksi PostgreSQL gagal:

- Pastikan PostgreSQL sedang berjalan.
- Pastikan database `nutrifit` sudah dibuat.
- Pastikan `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, dan `POSTGRES_DATABASE` benar.

Jika port Streamlit sudah dipakai:

```bash
streamlit run app.py --server.port 8502
```

Lalu buka:

```text
http://localhost:8502
```

## 17. Urutan Cepat dari Nol

Contoh urutan untuk MySQL:

```bash
cd "RecommendFood&Training"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 schema_data/import_csv_to_db.py
python3 schema_data/import_json_to_db.py
streamlit run app.py
```

Sebelum menjalankan import, pastikan isi `.env` sudah sesuai koneksi database lokal.
