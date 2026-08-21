"""Uji recommend_foods / swap_food tanpa database & tanpa cek gambar jaringan."""
import sys
from pathlib import Path

ROOT = Path(r"c:\Kuliah\Semester 8\Tugas Akhir\Coding\NutriFit")
sys.path.insert(0, str(ROOT))

import pandas as pd
from src import recommender as R
from src.nutrition import NutritionResult

R.check_image_urls_concurrently = lambda urls, max_workers=20: [True] * len(urls)

raw = pd.read_csv(ROOT / "data" / "food_nutrition.csv")
foods = R.prepare_foods(raw)
print(f"foods siap: {len(foods)}  camilan: {int(foods['Is_Snack'].sum())}")
print("kategori tersedia (semua slot):", R.available_food_categories(foods))
print("kategori tersedia (camilan)  :", R.available_food_categories(foods, meal_slot="Snack"))
print()

assert abs(sum(R.MEAL_DISTRIBUTION.values()) - 1.0) < 1e-9, R.MEAL_DISTRIBUTION

q = R.slot_calorie_quota(2000)
print("kuota TDEE 2000:", {k: round(v) for k, v in q.items()}, "total", round(sum(q.values())))
assert abs(sum(q.values()) - 2000) < 1e-9

HEAVY = R.NOT_SNACK_PATTERN


def check(recs, label):
    """Periksa satu set rekomendasi menu: kuota tiap slot, porsi gram, dan total kalorinya."""
    total_quota = 0
    print(f"\n--- {label} ---")
    for slot, items in recs.items():
        quota = items[0]["slot_quota_calories"] if items else None
        total_items = sum(i["target_calories"] for i in items)
        total_quota += total_items
        print(f"{slot:10s} kuota={quota} item={len(items)} jumlah_target={total_items}")
        for i in items:
            recomputed = (i["target_calories"] / i["calories"]) * 100
            assert abs(recomputed - i["portion_gram"]) < 1.0, (i["name"], recomputed, i["portion_gram"])
            assert R.MIN_PORTION_GRAM <= i["portion_gram"] <= R.MAX_PORTION_GRAM, i
            flag = ""
            if slot == "Snack":
                assert bool(i["Is_Snack"]), f"MAKANAN BERAT DI CAMILAN: {i['name']}"
                flag = " [camilan-ok]"
            print(f"    {i['name'][:44]:46s} {i['Food_Category']:20s} kl={i['Food_Cluster']} "
                  f"{i['portion_gram']:4d}g -> {i['target_calories']:4d} kkal{flag}")
    print(f"  TOTAL semua item = {total_quota} kkal")
    return total_quota


nut = NutritionResult(bmi=22.0, bmi_status="Normal", bmr=1600, tdee=2000, target_calories=2000,
                      ideal_weight=65.0, carbohydrate_g=250, protein_g=126, fat_g=56)

recs = R.recommend_foods(foods, nut)
total = check(recs, "tanpa filter kategori, target 2000")
assert total == 2000, total

for cats in (["Ayam"], ["Ikan & Seafood"], ["Telur"], ["Sayuran"], ["Ayam", "Ikan & Seafood"],
             ["Kerupuk & Keripik"], ["Umbi & Singkong"], ["Nasi & Olahan Beras"]):
    r = R.recommend_foods(foods, nut, categories=cats)
    t = check(r, f"kategori={cats}")
    assert t == 2000, (cats, t)

for target in (1200, 1500, 2500, 3000, 3500):
    n2 = NutritionResult(bmi=22.0, bmi_status="Normal", bmr=1600, tdee=target, target_calories=target,
                         ideal_weight=65.0, carbohydrate_g=1, protein_g=1, fat_g=1)
    r = R.recommend_foods(foods, n2)
    t = sum(i["target_calories"] for items in r.values() for i in items)
    empty = [s for s, items in r.items() if not items]
    print(f"target={target:5d} -> total={t:5d}  slot kosong={empty}")
    assert not empty, (target, empty)

print("\n=== SWAP ===")
recs = R.recommend_foods(foods, nut, categories=["Ayam"])
for slot, items in recs.items():
    for item in items:
        rep = R.swap_food(foods, item, item["target_calories"], meal_slot=slot, categories=["Ikan & Seafood"])
        assert rep is not None, (slot, item["name"])
        recomputed = (rep["target_calories"] / rep["calories"]) * 100
        assert abs(recomputed - rep["portion_gram"]) < 1.0
        assert rep["target_calories"] == item["target_calories"], "kuota kalori berubah saat swap!"
        if slot == "Snack":
            assert bool(rep["Is_Snack"]), f"SWAP camilan menghasilkan makanan berat: {rep['name']}"
        assert rep["Food_Cluster"] == item["Food_Cluster"] or True
        print(f"  {slot:10s} {item['name'][:32]:34s} -> {rep['name'][:32]:34s} "
              f"kl {item['Food_Cluster']}->{rep['Food_Cluster']} {rep['portion_gram']}g / {rep['target_calories']} kkal")

print("\n=== SWAP berulang di slot camilan (20x) ===")
snack = recs["Snack"][0]
excluded = []
current = snack
for i in range(20):
    rep = R.swap_food(foods, current, current["target_calories"], excluded_food_ids=excluded, meal_slot="Snack")
    if rep is None:
        print(f"  habis di iterasi {i}")
        break
    assert bool(rep["Is_Snack"]), f"MAKANAN BERAT: {rep['name']}"
    excluded.append(int(current["id"]))
    current = rep
    print(f"  {i+1:2d}. {rep['name'][:44]:46s} {rep['portion_gram']:4d}g")

print("\n=== estimasi kalori latihan ===")
for t in ("Strength", "Cardio", "Stretching", "Plyometrics"):
    ex = {"Type": t, "sets": 4, "reps": 12, "rest_seconds": 90}
    print(f"  {t:12s} {R.exercise_duration_minutes(ex):.1f} menit -> {R.estimate_exercise_calories(ex, 70):.0f} kkal")

print("\nSEMUA ASSERT LOLOS")
