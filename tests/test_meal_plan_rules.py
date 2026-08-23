"""Uji aturan susunan menu harian.

Satu makanan pokok per slot, camilan satu item, sarapan yang pantas, kudapan manis
tidak mengisi slot makan berat, dan total kalori persis sama dengan target.
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
# Templatenya kini satu per tujuan, jadi kedua aturan di bawah diperiksa pada
# KETIGANYA -- camilan satu item, dan jumlah item sama supaya ukuran porsinya
# sebanding antar tujuan.
assert set(R.MEAL_TEMPLATES) == {"Lose Weight", "Maintain Weight", "Gain Weight"}, \
    sorted(R.MEAL_TEMPLATES)
jumlah_item = set()
for tujuan, template in R.MEAL_TEMPLATES.items():
    assert set(template) == set(R.MEAL_DISTRIBUTION), f"{tujuan}: slot tak lengkap {sorted(template)}"
    assert len(template[R.SNACK_SLOT]) == 1, f"{tujuan}: camilan {template[R.SNACK_SLOT]}"
    jumlah_item.add(sum(len(peran) for peran in template.values()))
assert len(jumlah_item) == 1, f"jumlah item berbeda antar tujuan: {jumlah_item}"
assert abs(sum(R.MEAL_DISTRIBUTION.values()) - 1.0) < 1e-9
print(f"   {len(R.MEAL_TEMPLATES)} template, camilan 1 item, {jumlah_item.pop()} item/hari, proporsi 100%")

print("\n== tujuan mengubah susunan peran gizi, bukan cuma gramasi ==")
_susunan = {
    tujuan: sorted(peran for slot in template.values() for peran in slot)
    for tujuan, template in R.MEAL_TEMPLATES.items()
}
assert _susunan["Lose Weight"] != _susunan["Gain Weight"], _susunan
assert "D" not in _susunan["Lose Weight"], "protein berlemak tidak boleh masuk menu penurunan berat"
assert "D" in _susunan["Gain Weight"], "menu penambahan berat kehilangan protein berlemak"
for tujuan, susunan in _susunan.items():
    print(f"   {tujuan:16s} {''.join(susunan)}")

print("\n== satu makanan pokok per slot, camilan satu item, total presisi ==")
diperiksa = 0
for gender, berat, tinggi, umur, aktivitas, tujuan in PROFIL:
    gizi = calculate_nutrition_targets(
        gender=gender, weight_kg=berat, height_cm=tinggi, age=umur,
        activity_level=aktivitas, fitness_goal=tujuan,
    )
    for pref in PREFERENSI:
        menu = R.recommend_foods(foods, gizi, categories=pref, fitness_goal=tujuan)
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

print("\n== kudapan manis tidak boleh mengisi slot makan berat ==")
# Dilaporkan dari pemakaian nyata: "kue dadar gulung" muncul sebagai menu MAKAN
# SIANG. Ia jajanan pasar -- angka gizinya boleh saja cocok untuk slot itu,
# tetapi bentuk sajiannya bukan komponen makan berat.
KUDAPAN = ["kue", "bolu", "brownies", "klepon", "onde", "nagasari", "cucur",
           "serabi", "apem", "bikang", "lupis", "wingko", "bakpia", "donat",
           "puding", "cendol", "kolak", "ceriping", "getuk", "dodol", "jenang",
           "wajik", "geplak", "permen", "es krim", "manisan", "biskuit",
           "kerupuk", "krupuk", "keripik", "kripik", "emping", "rempeyek",
           "intip", "renggi", "kecimpring", "sale", "brondong", "rengginang"]
diperiksa_slot = 0
for slot in R.MAIN_MEAL_SLOTS:
    kolam = R.slot_candidate_pool(foods, slot)
    bocor = [n for n in kolam["name"] if any(k in str(n).lower() for k in KUDAPAN)]
    assert not bocor, f"kudapan lolos ke kolam {slot}: {bocor[:8]}"
    assert len(kolam) > 300, f"kolam {slot} terlalu sempit: {len(kolam)}"
    diperiksa_slot += 1
    print(f"   {slot:<10} {len(kolam)} kandidat, nol kudapan")

# Pagar itu tidak boleh mengosongkan slot mana pun pada menu yang sesungguhnya.
kategori_uji = [k for k in R.available_food_categories(foods) if k != R.OTHER_CATEGORY]
tidak_penuh = []
for gender, berat, tinggi, umur, aktivitas, tujuan in PROFIL:
    gizi = calculate_nutrition_targets(
        gender=gender, weight_kg=berat, height_cm=tinggi, age=umur,
        activity_level=aktivitas, fitness_goal=tujuan,
    )
    for kategori in [None] + kategori_uji:
        menu = R.recommend_foods(
            foods, gizi, categories=None if kategori is None else [kategori],
            fitness_goal=tujuan,
        )
        for slot, items in menu.items():
            if not items:
                tidak_penuh.append((tujuan, kategori, slot))
            for i in items:
                if slot in R.MAIN_MEAL_SLOTS:
                    rendah = str(i["name"]).lower()
                    assert not any(k in rendah for k in KUDAPAN), (
                        f"{slot} berisi kudapan '{i['name']}' "
                        f"pada preferensi {kategori}"
                    )
assert not tidak_penuh, f"slot kosong setelah pagar dipasang: {tidak_penuh[:8]}"
print(f"   nol kudapan di slot makan berat, dan nol slot kosong "
      f"dari {len(PROFIL) * (len(kategori_uji) + 1)} menu harian")

print("\n== slot camilan tetap punya isi ==")
camilan_kolam = R.slot_candidate_pool(foods, R.SNACK_SLOT)
assert len(camilan_kolam) > 100, f"kolam camilan terlalu sempit: {len(camilan_kolam)}"
# Yang dibuang dari slot makan berat harus tetap bisa muncul sebagai camilan --
# kalau tidak, pagarnya bukan memindahkan melainkan menghilangkan.
nama_camilan = camilan_kolam["name"].astype(str).str.lower()
for wajib in ["kerupuk", "keripik", "getuk", "kue"]:
    assert nama_camilan.str.contains(wajib, regex=False).any(), (
        f"'{wajib}' hilang sama sekali, bukan sekadar dipindah ke slot camilan"
    )
print(f"   {len(camilan_kolam)} kandidat camilan; kerupuk/keripik/getuk/kue tetap ada")

print("\n== 'kue dadar gulung' tidak lagi berlabel Telur ==")
# Pola kategori Telur dulu memuat kata "dadar", sehingga dua kudapan manis
# berlabel Telur di kartu menu padahal tidak ada telurnya sebagai bahan utama.
assert "Telur" not in R.food_categories_for_name("kue dadar gulung"), \
    R.food_categories_for_name("kue dadar gulung")
assert "Telur" not in R.food_categories_for_name("kue dadar")
for telur_asli in ["telur dadar", "Telur Ayam dadar", "Telur Bebek dadar"]:
    assert "Telur" in R.food_categories_for_name(telur_asli), telur_asli
print("   kue dadar bukan Telur; telur dadar yang sungguhan tetap Telur")

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
