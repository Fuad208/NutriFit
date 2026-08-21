"""Uji core/claims.py memakai schema Postgres terisolasi (bukan data asli)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from _isolasi import pakai_schema_uji  # noqa: E402

pakai_schema_uji("claims")

from datetime import datetime  # noqa: E402
from uuid import uuid4  # noqa: E402

from src.database import MEAL_STORE, WORKOUT_STORE, append_record, ensure_database, load_records  # noqa: E402
from src.core import claims  # noqa: E402
from src.core.progress import MEAL, WORKOUT  # noqa: E402

ensure_database()
USER = {"user_id": "u1", "email": "u1@gmail.com"}
now = lambda: datetime.now().isoformat(timespec="seconds")  # noqa: E731


def meal_item(food_id, name, kcal, gram, protein, fat, carb, eaten=False):
    """Bentuk satu item menu contoh selengkap yang dihasilkan rekomendasi asli."""
    return {
        "id": food_id, "name": name, "target_calories": kcal, "portion_gram": gram,
        "proteins": protein, "fat": fat, "carbohydrate": carb,
        "calories": round(kcal / gram * 100), "Food_Cluster": "B",
        "Food_Category": "Ayam", "is_eaten": eaten,
    }


append_record(MEAL_STORE, {
    "id": str(uuid4()), "user_id": "u1", "email": "u1@gmail.com", "preference": ["Ayam"],
    "recommendations": {
        "Breakfast": [meal_item(1, "Ayam goreng", 250, 100, 20.0, 10.0, 5.0)],
        "Snack": [meal_item(2, "Ubi rebus", 200, 175, 1.0, 0.2, 30.0)],
    },
    "created_at": now(),
})

append_record(WORKOUT_STORE, {
    "id": str(uuid4()), "user_id": "u1", "email": "u1@gmail.com", "filters": {"body_part": "Dada"},
    "recommendations": [
        {"Title": "Barbell Bench Press", "Type": "Strength", "sets": 4, "reps": 12, "rest_seconds": 90},
        {"Title": "Push-Up", "Type": "Strength", "sets": 3, "reps": 15, "rest_seconds": 60},
    ],
    "created_at": now(),
})


def reload():
    """Baca ulang record menu dan latihan dari penyimpanan uji."""
    return {MEAL: load_records(MEAL_STORE), WORKOUT: load_records(WORKOUT_STORE)}


records = reload()
s = claims.claim_summary(records, 70)
print("awal:", s["meals_claimed"], "/", s["meals_total"], "menu |",
      s["workouts_claimed"], "/", s["workouts_total"], "latihan |",
      "konsumsi", s["consumed"], "| terbakar", round(s["burned"], 1))
assert s["meals_total"] == 2 and s["workouts_total"] == 2
assert s["consumed"]["calories"] == 0 and s["burned"] == 0

# --- klaim satu menu ---
assert claims.set_meal_claim(USER, records[MEAL], "Breakfast", 1, True)
records = reload()
s = claims.claim_summary(records, 70)
print("setelah klaim Ayam goreng:", s["consumed"])
assert s["meals_claimed"] == 1
assert s["consumed"]["calories"] == 250
# porsi 100 g -> makro persis nilai per-100g dataset
assert abs(s["consumed"]["protein_g"] - 20.0) < 1e-6, s["consumed"]

# --- klaim menu kedua: makro HARUS diskalakan ke porsi (175 g) ---
assert claims.set_meal_claim(USER, records[MEAL], "Snack", 2, True)
records = reload()
s = claims.claim_summary(records, 70)
print("setelah klaim Ubi rebus:", s["consumed"])
assert s["consumed"]["calories"] == 450
assert abs(s["consumed"]["carbohydrate_g"] - (5.0 + 30.0 * 1.75)) < 1e-6, s["consumed"]

# --- batalkan klaim ---
assert claims.set_meal_claim(USER, records[MEAL], "Breakfast", 1, False)
records = reload()
s = claims.claim_summary(records, 70)
print("setelah batal klaim Ayam goreng:", s["consumed"])
assert s["consumed"]["calories"] == 200

# --- menu baru dibuat sore hari: item lama yang sudah dimakan tetap terhitung ---
append_record(MEAL_STORE, {
    "id": str(uuid4()), "user_id": "u1", "email": "u1@gmail.com", "preference": ["Ikan & Seafood"],
    "recommendations": {"Lunch": [meal_item(9, "Ikan bakar", 300, 150, 25.0, 8.0, 2.0)]},
    "created_at": now(),
})
records = reload()
s = claims.claim_summary(records, 70)
print("setelah buat menu baru:", s["consumed"], "| rencana:", list(s["meal_plan"]))
assert s["consumed"]["calories"] == 200, "klaim lama hilang saat menu disusun ulang"
assert list(s["meal_plan"]) == ["Lunch"], s["meal_plan"]

# --- klaim latihan ---
assert claims.set_workout_claim(USER, records[WORKOUT], "Barbell Bench Press", True)
records = reload()
s = claims.claim_summary(records, 70)
print("setelah klaim latihan:", s["workouts_claimed"], "/", s["workouts_total"],
      "terbakar", round(s["burned"], 1), "kkal")
assert s["workouts_claimed"] == 1
assert s["burned"] > 0

assert claims.set_workout_claim(USER, records[WORKOUT], "Push-Up", True)
records = reload()
s2 = claims.claim_summary(records, 70)
assert s2["burned"] > s["burned"]
print("dua latihan diklaim -> terbakar", round(s2["burned"], 1), "kkal")

assert claims.set_workout_claim(USER, records[WORKOUT], "Barbell Bench Press", False)
records = reload()
s3 = claims.claim_summary(records, 70)
assert s3["workouts_claimed"] == 1
print("setelah batal satu latihan -> terbakar", round(s3["burned"], 1), "kkal")

# --- berat badan tidak ada: tidak boleh meledak ---
assert claims.claim_summary(records, None)["burned"] == 0

# --- klaim item yang tidak ada di rencana ditolak ---
assert not claims.set_meal_claim(USER, records[MEAL], "Dinner", 99, True)
assert not claims.set_workout_claim(USER, records[WORKOUT], "Tidak Ada", True)

print("\nSEMUA ASSERT CLAIMS LOLOS")
