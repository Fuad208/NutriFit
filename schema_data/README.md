# Schema Data

Folder ini berisi script Python untuk membuat tabel dan insert data ke database SQL yang aktif di `.env`.

## Dataset CSV

Script:

```bash
python3 schema_data/import_csv_to_db.py
```

Tabel dataset yang dibuat:

- `food_nutrition` dari `data/food_nutrition.csv`
- `gym_members` dari `data/gym_members.csv`
- `training_program` dari `data/training_program.csv`

Default script akan mengosongkan tabel dataset terlebih dahulu lalu insert ulang data CSV. Ini mode paling aman untuk refresh data:

```bash
python3 schema_data/import_csv_to_db.py
```

Untuk append tanpa truncate:

```bash
python3 schema_data/import_csv_to_db.py --append
```

Pada mode `--append`, tabel yang punya primary key dari CSV (`food_nutrition.id` dan `training_program.program_id`) memakai upsert, jadi data lama dengan primary key yang sama akan di-update dan tidak memunculkan error duplicate entry.

## Database JSON

Script:

```bash
python3 schema_data/import_json_to_db.py
```

Tabel aplikasi yang dibuat:

- `users` dari `database/user.json`
- `calorie_records` dari `database/calorie.json`
- `meal_recommendations` dari `database/meal_recommendation.json`
- `workout_recommendations` dari `database/workout_recommendation.json`

Default script JSON memakai upsert, jadi aman dijalankan berulang tanpa duplicate primary key. Untuk menghapus isi tabel JSON-backed terlebih dahulu lalu import ulang:

```bash
python3 schema_data/import_json_to_db.py --replace
```

Switch database tetap mengikuti `.env`:

```env
MYSQL=true
POSTGRES=false
```

atau:

```env
MYSQL=false
POSTGRES=true
```
