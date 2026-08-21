"""Aturan susunan menu harian: satu makanan pokok per slot, camilan satu item,
sarapan yang pantas, dan total kalori yang tetap persis sama dengan target.

LATAR MASALAHNYA. Dengan preferensi "Nasi", slot makan siang pernah berisi
"Nasi", "Dendeng daging sapi", DAN "Nasi goreng" sekaligus -- dua sumber
karbohidrat utama di satu piring. Porsinya memang berbeda, tetapi susunan itu
bukan sepiring makan yang masuk akal.

Slot camilan juga pernah berisi dua item, sehingga terbaca seperti waktu makan
keempat alih-alih selingan.
"""
import sys
import warnings
from pathlib import Path

ROOT = Path(r"c:\Kuliah\Semester 8\Tugas Akhir\Coding\NutriFit")
sys.path.insert(0, str(ROOT))

warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

import src.recommender as R  # noqa: E402
from src.nutrition import calculate_nutrition_targets  # noqa: E402

foods = R.prepare_foods(R.load_dataset_tables()[1])

PROFIL = [
    ("Male", 70, 175, 22, "Medium", "Lose Weight"),
    ("Female", 55, 160, 21, "Low", "Maintain Weight"),
    ("Male", 90, 180, 35, "High", "Gain Weight"),
    ("Female", 48, 155, 19, "Very High", "Gain Weight"),
]
PREFERENSI = [
    [], ["Nasi & Olahan Beras"], ["Ayam"], ["Mie & Bihun"],
    ["Ikan & Seafood"], ["Nasi & Olahan Beras", "Ayam"],
]

print("== template slot ==")
assert len(R.MEAL_TEMPLATE[R.SNACK_SLOT]) == 1, R.MEAL_TEMPLATE[R.SNACK_SLOT]
assert abs(sum(R.MEAL_DISTRIBUTION.values()) - 1.0) < 1e-9
print(f"   camilan {len(R.MEAL_TEMPLATE[R.SNACK_SLOT])} item, proporsi total 100%")

print("\n== satu makanan pokok per slot, camilan satu item, total presisi ==")
diperiksa = 0
for gender, berat, tinggi, umur, aktivitas, tujuan in PROFIL:
    gizi = calculate_nutrition_targets(
        gender=gender, weight_kg=berat, height_cm=tinggi, age=umur,
        activity_level=aktivitas, fitness_goal=tujuan,
    )
    for pref in PREFERENSI:
        menu = R.recommend_foods(foods, gizi, categories=pref)
        diperiksa += 1

        assert len(menu[R.SNACK_SLOT]) == 1, (
            f"camilan {len(menu[R.SNACK_SLOT])} item pada preferensi {pref}"
        )

        for slot, items in menu.items():
            if not items:
                continue
            pokok = int(R.is_staple_food(pd.DataFrame(items)).sum())
            assert pokok <= 1, (
                f"{slot} berisi {pokok} makanan pokok pada preferensi {pref}: "
                + ", ".join(str(i["name"]) for i in items)
            )

        total = sum(i["target_calories"] for items in menu.values() for i in items)
        assert total == gizi.target_calories, f"{total} != {gizi.target_calories}"
print(f"   {diperiksa} kombinasi profil x preferensi lolos seluruhnya")

print("\n== sarapan tidak boleh berupa gula-gula atau kerupuk ==")
sarapan = R.slot_candidate_pool(foods, R.BREAKFAST_SLOT)
nama = sarapan["name"].astype(str).str.lower()
TERLARANG = ["permen", "dodol", "es krim", "kerupuk", "krupuk", "keripik",
             "kripik", "emping", "rempeyek", "biskuit", "wajik", "geplak"]
bocor = [n for n in sarapan["name"] if any(k in str(n).lower() for k in TERLARANG)]
assert not bocor, f"tidak pantas untuk sarapan: {bocor[:8]}"
print(f"   {len(sarapan)} kandidat sarapan, tidak satu pun gula-gula/kerupuk")

print("\n== sarapan yang WAJAR harus tetap tersedia ==")
WAJAR = ["nasi", "bubur", "roti", "telur", "lontong", "mie", "soto"]
tersedia = {k: int(nama.str.contains(k, regex=False).sum()) for k in WAJAR}
for k, jumlah in tersedia.items():
    assert jumlah > 0, f"tidak ada kandidat sarapan mengandung '{k}'"
print("   " + ", ".join(f"{k}={j}" for k, j in tersedia.items()))

print("\n== penukaran tetap menghormati aturan slot ==")
gizi = calculate_nutrition_targets(
    gender="Male", weight_kg=70, height_cm=175, age=22,
    activity_level="Medium", fitness_goal="Lose Weight",
)
menu = R.recommend_foods(foods, gizi)
camilan = menu[R.SNACK_SLOT][0]
pengganti = R.swap_food(foods, camilan, camilan["target_calories"], meal_slot=R.SNACK_SLOT)
assert pengganti is not None, "tidak ada pengganti camilan"
assert bool(pengganti.get("Is_Snack", False)), f"pengganti bukan camilan: {pengganti['name']}"
assert pengganti["target_calories"] == camilan["target_calories"], "kuota kalori berubah"
print(f"   {camilan['name']} -> {pengganti['name']} "
      f"({pengganti['portion_gram']} g, tetap {pengganti['target_calories']} kkal)")

print("\nSEMUA ASSERT ATURAN MENU LOLOS")
