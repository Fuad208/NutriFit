# Schema Data

Skrip Python untuk membuat tabel dan mengisi data ke database PostgreSQL
(Supabase) yang dikonfigurasi di `.env`.

## Dataset CSV

```bash
python3 schema_data/import_csv_to_db.py
```

Tabel dataset yang dibuat:

- `food_nutrition` dari `data/food_nutrition.csv`
- `gym_members` dari `data/gym_members.csv`
- `training_program` dari `data/training_program.csv`

Secara bawaan skrip mengosongkan tabel dataset lebih dulu lalu memasukkan ulang
isi CSV. Ini mode paling aman untuk menyegarkan data.

Untuk menambah tanpa mengosongkan:

```bash
python3 schema_data/import_csv_to_db.py --append
```

Pada mode `--append`, tabel yang punya primary key dari CSV
(`food_nutrition.id` dan `training_program.program_id`) memakai upsert, jadi
baris lama dengan primary key yang sama akan diperbarui dan tidak memunculkan
error duplicate key.

## Tabel aplikasi

Tabel `users`, `calorie_records`, `meal_recommendations`, dan
`workout_recommendations` **tidak perlu diimpor**. Semuanya dibuat dan
diselaraskan otomatis oleh `ensure_schema()` di `src/database.py` setiap kali
aplikasi dijalankan.

## Konfigurasi

```env
POSTGRES_HOST=...
POSTGRES_PORT=5432
POSTGRES_USER=...
POSTGRES_PASSWORD=...
POSTGRES_DATABASE=postgres

# Opsional. Default 'public'. Skrip di tests/ mengisinya sendiri
# dengan schema sekali-pakai supaya tidak menyentuh data asli.
# POSTGRES_SCHEMA=public
```

## Skrip lain

| Skrip | Kegunaan |
|---|---|
| `migrate_user_clusters.py` | Hitung ulang klaster seluruh pengguna terhadap model aktif (`--terapkan` untuk menulis) |
| `merge_foods_dataset.py` | Gabungkan dataset menu tambahan ke `food_nutrition.csv` (`--tulis`, `--db`) |
| `repair_food_images.py` | Cari gambar pengganti untuk menu yang tautannya mati (`--tulis`, `--db`) |
| `fetch_lottie_assets.py` | Unduh ulang animasi Lottie dan pemutarnya ke `assets/` |
