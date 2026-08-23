"""Uji kompatibilitas record lama: profil tanpa kolom baru tetap bisa dibaca dan dirender."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from _isolasi import pakai_schema_uji  # noqa: E402

pakai_schema_uji("legacy")

import pandas as pd  # noqa: E402
from src import recommender as R  # noqa: E402

R.check_image_urls_concurrently = lambda urls, max_workers=20: [True] * len(urls)
_members = pd.read_csv(ROOT / "data" / "gym_members.csv")
_foods = pd.read_csv(ROOT / "data" / "food_nutrition.csv")
_ex = pd.read_csv(ROOT / "data" / "training_program.csv").head(120)
R.load_dataset_tables = lambda: (_members, _foods, _ex)

from datetime import datetime  # noqa: E402
from uuid import uuid4  # noqa: E402

from src.database import (  # noqa: E402
    CALORIE_STORE, MEAL_STORE, WORKOUT_STORE, append_record, ensure_database, save_users,
)
from src.nutrition import calculate_nutrition_targets  # noqa: E402

ensure_database()
USER_ID, EMAIL = "legacy-user", "legacy@gmail.com"
nutrition = calculate_nutrition_targets(
    gender="Male", weight_kg=70, height_cm=175, age=22,
    activity_level="Medium", fitness_goal="Maintain Weight",
)
profile = {
    "gender": "Male", "age": 22, "weight_kg": 70.0, "height_cm": 175.0,
    "activity_level": "Medium", "experience_level": "Intermediate",
    "fitness_goal": "Maintain Weight", "bmi": nutrition.bmi, "user_cluster": 1,
}
save_users({EMAIL: {
    "user_id": USER_ID, "email": EMAIL, "name": "Legacy", "role": "user",
    "password": None, "password_hash": "x", "auth_provider": "local",
    "email_verified": True, "gender": "Male", "birth_date": "2004-01-01",
    "profile": profile, "nutrition": nutrition.__dict__,
}})
now = lambda: datetime.now().isoformat(timespec="seconds")  # noqa: E731
append_record(CALORIE_STORE, {
    "id": str(uuid4()), "user_id": USER_ID, "email": EMAIL,
    "profile": profile, "nutrition": nutrition.__dict__, "created_at": now(),
})


def item_lama(food_id, name, kcal, gram, cal100):
    """Bentuk item SEBELUM perubahan hari ini: tanpa Is_Snack, Food_Category,
    meal_slot, slot_quota_calories, slot_share, maupun category_match."""
    return {
        "id": food_id, "name": name, "calories": cal100,
        "proteins": 12.0, "fat": 5.0, "carbohydrate": 30.0,
        "image": "", "Food_Cluster": "B", "CBF_Text": f"{name} cluster B",
        "portion_gram": gram, "target_calories": kcal,
        "similarity_score": 0.12, "is_eaten": False,
    }


# Distribusi LAMA: Breakfast .25 / Lunch .35 / Snack .10 / Dinner .30,
# dan slot Snack hanya berisi SATU item -- termasuk makanan berat "Nasi goreng".
append_record(MEAL_STORE, {
    "id": str(uuid4()), "user_id": USER_ID, "email": EMAIL,
    "preference": ["ayam", "telur"],  # kata kunci bebas, bukan label kategori
    "recommendations": {
        "Breakfast": [item_lama(1, "Ayam goreng paha", 290, 120, 242),
                      item_lama(2, "Telur ayam dadar", 290, 116, 251)],
        "Lunch": [item_lama(3, "Nasi", 271, 151, 180),
                  item_lama(4, "Soto Betawi masakan", 271, 200, 135),
                  item_lama(5, "Sayur asem", 271, 300, 90)],
        "Snack": [item_lama(6, "Nasi Goreng", 232, 93, 250)],
        "Dinner": [item_lama(7, "Ikan mas goreng", 348, 150, 232),
                   item_lama(8, "Kangkung tumis", 348, 300, 116)],
    },
    "created_at": now(),
})

append_record(WORKOUT_STORE, {
    "id": str(uuid4()), "user_id": USER_ID, "email": EMAIL,
    "filters": {"body_part": "Dada", "workout_type": "Strength",
                "equipment_preference": "Any", "experience_level": "Intermediate",
                "fitness_goal": "Maintain Weight", "limit": 3},
    # Tanpa is_done -- kolom itu baru ada setelah fitur klaim.
    "recommendations": [
        {"Title": "Barbell Bench Press", "Desc": "d", "Type": "Strength",
         "BodyPart": "Chest", "Equipment": "Barbell", "Level": "Intermediate",
         "sets": 3, "reps": 12, "rest_seconds": 75, "Similarity": 0.4},
    ],
    "created_at": now(),
})

from streamlit.testing.v1 import AppTest  # noqa: E402

BASE = {"authenticated": True, "current_user": EMAIL,
        "nutrition": nutrition, "profile": profile}


def buka(page, extra=None):
    """Jalankan satu halaman dengan state uji dan gagalkan bila ada exception."""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.run()
    for k, v in {**BASE, "page": page, **(extra or {})}.items():
        at.session_state[k] = v
    at.run()
    if at.exception:
        for e in at.exception:
            print(f"  !! EXCEPTION di {page}: {e.value}")
        raise AssertionError(f"{page} error pada record lama")
    return at


print("== Rekomendasi Menu memulihkan record lama ==")
at = buka("Meal Recommendation")
assert at.session_state["meal_from_storage"], "record lama tidak dipulihkan"
recs = at.session_state["food_recommendations"]
print("   slot dipulihkan:", {s: len(v) for s, v in recs.items()})
assert len(recs["Snack"]) == 1, "struktur lama berubah saat dipulihkan"

teks = [m.value or "" for m in at.markdown]
for slot in ("Sarapan", "Makan Siang", "Camilan", "Makan Malam"):
    assert any(slot in t for t in teks), f"slot {slot} tidak dirender"
print("   keempat slot dirender tanpa error")

# Kata kunci bebas lama BUKAN nama kategori, jadi filter harus kembali kosong
# (menunya tetap tampil).
assert at.session_state["meal_categories"] == [], at.session_state["meal_categories"]
print("   preferensi teks bebas lama diabaikan dengan benar:",
      at.session_state["meal_categories"])

print("== Tukar item lama (tanpa meal_slot di record) ==")
tombol = [b for b in at.button if (b.label or "") == "Tukar Sekarang"]
assert tombol, "tombol tukar tidak ada"
at2 = tombol[-1].click().run()   # item terakhir = slot Makan Malam
assert not at2.exception, [e.value for e in at2.exception]
print("   tukar pada record lama berhasil tanpa error")

print("== Tukar item di slot Camilan lama yang berisi makanan berat ==")
at3 = buka("Meal Recommendation")
snack_id = at3.session_state["food_recommendations"]["Snack"][0]["id"]
# Dicari lewat key widget-nya, bukan lewat urutan tombol: urutan render bisa
# berubah dan menebak indeks akan menguji slot yang salah tanpa ketahuan.
tombol_snack = [b for b in at3.button
                if f"swap_Snack_{snack_id}" in (b.proto.id or "")]
assert tombol_snack, (
    f"tombol tukar untuk slot Camilan (id={snack_id}) tidak ditemukan; "
    "key widget mungkin berubah"
)
at4 = tombol_snack[0].click().run()
assert not at4.exception, [e.value for e in at4.exception]
snack_baru = at4.session_state["food_recommendations"]["Snack"][0]
print(f"   Nasi Goreng -> {snack_baru['name']}")
assert bool(snack_baru.get("Is_Snack")), \
    f"tukar dari record lama menghasilkan makanan berat: {snack_baru['name']}"

print("== Dashboard membaca record lama ==")
at5 = buka("Home")
labels = [c.label for c in at5.checkbox]
print("   checkbox klaim:", labels)
assert labels, "tidak ada checkbox klaim dari record lama"
at6 = at5.checkbox[0].check().run()
assert not at6.exception, [e.value for e in at6.exception]
print("   klaim menu lama OK")

latihan = [c for c in at5.checkbox if "kkal)" in (c.label or "") and "·" not in (c.label or "")]
assert latihan, "latihan lama (tanpa is_done) tidak muncul sebagai checkbox"
print("   latihan lama muncul:", [c.label for c in latihan])

print("== Rekomendasi Latihan memulihkan record lama ==")
at7 = buka("Workout Recommendation")
assert at7.session_state["workout_from_storage"], "program lama tidak dipulihkan"
print("   program latihan lama dipulihkan tanpa error")

print("\nSEMUA ASSERT RECORD LAMA LOLOS")
