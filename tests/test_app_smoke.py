"""Smoke test halaman NutriFit dengan Streamlit AppTest (schema Postgres terisolasi)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from _isolasi import pakai_schema_uji  # noqa: E402

pakai_schema_uji("smoke")

import pandas as pd  # noqa: E402
from src import recommender as R  # noqa: E402

R.check_image_urls_concurrently = lambda urls, max_workers=20: [True] * len(urls)
_members = pd.read_csv(ROOT / "data" / "gym_members.csv")
_foods = pd.read_csv(ROOT / "data" / "food_nutrition.csv")
# Pencocokan latihan <-> tutorial itu fuzzy O(n*m) dan lambat untuk 2918 baris,
# jadi tes ini memakai subset baris yang namanya PERSIS ada di dataset tutorial
# (dijamin punya video) plus cukup banyak latihan dada untuk mengisi filter awal.
import json as _json  # noqa: E402
import re as _re  # noqa: E402

_tut_names = {
    _re.sub(r"[^a-z0-9]+", " ", str(t.get("name", "")).lower()).strip()
    for t in _json.load(open(ROOT / "dataProgramTraining/data/exercises.json", encoding="utf-8"))
}
_all_ex = pd.read_csv(ROOT / "data" / "training_program.csv")
_norm = _all_ex["Title"].astype(str).str.lower().str.replace(r"[^a-z0-9]+", " ", regex=True).str.strip()
_ex = _all_ex[_norm.isin(_tut_names)].head(400)
print(f"[setup] latihan dengan nama sama persis di dataset tutorial: {len(_ex)}")
R.load_dataset_tables = lambda: (_members, _foods, _ex)

from datetime import datetime  # noqa: E402
from uuid import uuid4  # noqa: E402

from src.database import CALORIE_STORE, append_record, ensure_database, save_users  # noqa: E402
from src.nutrition import calculate_nutrition_targets  # noqa: E402

ensure_database()
USER_ID = "smoke-user"
EMAIL = "smoke@gmail.com"
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
    "user_id": USER_ID, "email": EMAIL, "name": "Smoke", "role": "user",
    "password_hash": "x", "auth_provider": "local", "email_verified": True,
    "gender": "Male", "birth_date": "2004-01-01",
    "profile": profile, "nutrition": nutrition.__dict__,
}})
append_record(CALORIE_STORE, {
    "id": str(uuid4()), "user_id": USER_ID, "email": EMAIL,
    "profile": profile, "nutrition": nutrition.__dict__,
    "created_at": datetime.now().isoformat(timespec="seconds"),
})

from streamlit.testing.v1 import AppTest  # noqa: E402

BASE_STATE = {
    "authenticated": True,
    "current_user": EMAIL,
    "nutrition": nutrition,
    "profile": profile,
}


def run_tamu(page):
    """Jalankan halaman untuk pengunjung yang BELUM login (masuk/daftar)."""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.run()
    at.session_state["authenticated"] = False
    at.session_state["current_user"] = None
    at.session_state["page"] = page
    at.run()
    if at.exception:
        for e in at.exception:
            print(f"  !! EXCEPTION on {page}: {e.value}")
        raise AssertionError(f"{page} melempar exception")
    return at


def run(page, extra=None, click=None):
    """Jalankan satu halaman aplikasi dengan state uji, gagalkan bila ada exception, lalu balas hasilnya."""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.run()
    for key, value in {**BASE_STATE, "page": page, **(extra or {})}.items():
        at.session_state[key] = value
    at.run()
    if at.exception:
        for e in at.exception:
            print(f"  !! EXCEPTION on {page}: {e.value}")
        raise AssertionError(f"{page} melempar exception")
    if click:
        matched = [b for b in at.button if click in (b.label or "")]
        assert matched, f"tombol '{click}' tidak ditemukan di {page}"
        matched[0].click().run()
        if at.exception:
            for e in at.exception:
                print(f"  !! EXCEPTION after clicking {click}: {e.value}")
            raise AssertionError(f"{page} melempar exception setelah klik '{click}'")
    return at


print("== Home ==")
at = run("Home")
print("   markdown blocks:", len(at.markdown), "| tombol:", len(at.button))
assert any("Riwayat Aktivitas" in (m.value or "") for m in at.markdown), "kartu riwayat tidak dirender"

print("== Meal Recommendation ==")
at = run("Meal Recommendation")
# Preferensi kini berupa kartu centang sumber protein, bukan daftar semua kategori.
pref = [c for c in at.checkbox if str(c.key or "").startswith("pref_")]
assert pref, "kartu preferensi sumber protein tidak dirender"
label = [c.label for c in pref]
print(f"   {len(pref)} pilihan sumber protein:", label)
for wajib in ("Ayam", "Daging Sapi", "Daging Kambing", "Telur", "Ikan & Seafood",
              "Olahan Kedelai", "Kacang-kacangan", "Sayur"):
    assert wajib in label, f"pilihan '{wajib}' tidak ada: {label}"
assert all(not c.value for c in pref), "seharusnya belum ada yang tercentang"

# Setiap sumber protein yang PUNYA menu di dataset harus ditawarkan -- kalau
# kategori baru muncul di dataset, uji ini yang mengingatkan.
_siap = R.prepare_foods(_foods)
_tersedia = set(R.available_food_categories(_siap))
_protein = {k for k in R.PROTEIN_PREFERENCE_CATEGORIES.values() if k in _tersedia}
_ditawarkan = {R.PROTEIN_PREFERENCE_CATEGORIES[l] for l in label}
assert _protein == _ditawarkan, f"tidak lengkap: kurang {_protein - _ditawarkan}"
print(f"   seluruh {len(_protein)} kategori protein yang ada di dataset ditawarkan")

# Sumber karbohidrat & pelengkap TIDAK boleh ikut ditawarkan.
for terlarang in ("Nasi & Olahan Beras", "Mie & Bihun", "Kerupuk & Keripik", "Buah"):
    assert terlarang not in label, f"'{terlarang}' bukan sumber protein: {label}"
print("   hanya sumber protein yang ditawarkan; karbohidrat & pelengkap tidak ikut")

at.checkbox(key="pref_Ayam").check().run()
assert not at.exception, [e.value for e in at.exception]
assert at.session_state["meal_categories"] == ["Ayam"], at.session_state["meal_categories"]
print("   mencentang Ayam tersimpan sebagai kategori dataset 'Ayam'")

at = run("Meal Recommendation", click="Buat Menu")
texts = [m.value or "" for m in at.markdown]
for slot in ("Sarapan", "Makan Siang", "Camilan", "Makan Malam"):
    assert any(slot in t for t in texts), f"slot {slot} tidak muncul"
print("   keempat slot dirender")
recs = at.session_state["food_recommendations"]
total = sum(i["target_calories"] for items in recs.values() for i in items)
print(f"   total target = {total} kkal (target harian {nutrition.target_calories:.0f} kkal)")
assert abs(total - nutrition.target_calories) <= 1
heavy = [i["name"] for i in recs["Snack"] if not i.get("Is_Snack")]
assert not heavy, f"makanan berat di slot camilan: {heavy}"
print("   camilan:", [i["name"] for i in recs["Snack"]])

print("== Home setelah menu dibuat (klaim) ==")
at = run("Home")
checkboxes = [c.label for c in at.checkbox]
print("   checkbox klaim:", checkboxes[:3], f"... total {len(checkboxes)}")
assert checkboxes, "tidak ada checkbox klaim di dashboard"
at.checkbox[0].check().run()
assert not at.exception, [e.value for e in at.exception]
print("   klaim menu OK")

print("== Workout Recommendation ==")
at = run("Workout Recommendation", click="Buat Program Latihan")
texts = [m.value or "" for m in at.markdown]
if not any("Program Latihan" in t for t in texts):
    print("   warning:", [w.value for w in at.warning])
    print("   info   :", [i.value for i in at.info])
    print("   markdown:", [t[:90] for t in texts][:8])
assert any("Program Latihan" in t for t in texts), "program latihan tidak dirender"
assert any("Latihan kekuatan untuk melatih" in t or "Latihan " in t for t in texts)
import re as _re2  # noqa: E402

print("   program latihan dirender, contoh kartu:")
for t in texts:
    if 'class="exercise-title"' in t:
        print("     ", _re2.sub(r"\s+", " ", _re2.sub(r"<[^>]+>", " | ", t)).strip()[:220])
        break

print("== Home: klaim latihan ==")
at = run("Home")
labels = [c.label for c in at.checkbox]
workout_boxes = [i for i, c in enumerate(at.checkbox) if "kkal)" in (c.label or "") and "·" not in (c.label or "")]
print("   semua checkbox:", labels)
assert workout_boxes, "checkbox klaim latihan tidak muncul di dashboard"

captions_before = [c.value for c in at.markdown if "card-caption" in (c.value or "")]
at.checkbox[workout_boxes[0]].check().run()
assert not at.exception, [e.value for e in at.exception]
captions_after = [c.value for c in at.markdown if "card-caption" in (c.value or "")]
print("   sebelum:", _re2.sub(r"<[^>]+>", "", captions_before[0]) if captions_before else "-")
print("   sesudah:", _re2.sub(r"<[^>]+>", "", captions_after[0]) if captions_after else "-")
assert any("latihan yang diklaim" in (c or "") for c in captions_after), \
    "kalori terbakar tidak masuk ke kartu Target Kalori Harian"

print("== Tukar menu lewat UI ==")
at = run("Meal Recommendation")
sebelum = {slot: [i["name"] for i in items]
           for slot, items in at.session_state["food_recommendations"].items()}
tombol_tukar = [b for b in at.button if (b.label or "") == "Tukar Sekarang"]
assert tombol_tukar, "tombol Tukar Sekarang tidak ditemukan (popover tidak dirender?)"
print(f"   {len(tombol_tukar)} tombol tukar tersedia")

at = tombol_tukar[0].click().run()
assert not at.exception, [e.value for e in at.exception]
sesudah = {slot: [i["name"] for i in items]
           for slot, items in at.session_state["food_recommendations"].items()}
berubah = [(s, a, b) for s in sebelum for a, b in zip(sebelum[s], sesudah[s]) if a != b]
assert berubah, f"tidak ada item yang berubah setelah tukar\n{sebelum}\n{sesudah}"
slot_berubah, lama, baru = berubah[0]
print(f"   {slot_berubah}: {lama} -> {baru}")

# Kuota kalori harian tidak boleh berubah gara-gara penukaran.
total_sesudah = sum(i["target_calories"]
                    for items in at.session_state["food_recommendations"].values()
                    for i in items)
assert total_sesudah == nutrition.target_calories, \
    f"total kalori berubah setelah tukar: {total_sesudah} != {nutrition.target_calories}"
print(f"   total tetap {total_sesudah} kkal")

for i in at.session_state["food_recommendations"]["Snack"]:
    assert bool(i["Is_Snack"]), f"tukar menghasilkan makanan berat di camilan: {i['name']}"

print("== Workout Tutorial (dengan tutorial) ==")
at = run("Workout Recommendation", click="Buat Program Latihan")
tombol_detail = [b for b in at.button if (b.label or "") == "Lihat Panduan"]
assert tombol_detail, "tombol Lihat Panduan tidak ditemukan"

# Susunan kartu rekomendasi: nama -> takaran -> chip -> inti gerakan, dan
# keterangannya harus RINGKAS (satu kalimat), bukan prosa dataset.
kartu = [m.value for m in at.markdown if 'class="exercise-head"' in (m.value or "")]
assert kartu, "kartu latihan tidak dirender dengan blok exercise-head"
contoh = kartu[0]
for penanda in ("exercise-title", "workout-dose", "chip-row", "exercise-desc"):
    assert penanda in contoh, f"{penanda} tidak ada di kartu latihan"
urutan = [contoh.index(p) for p in
          ("exercise-title", "workout-dose", "chip-row", "exercise-desc")]
assert urutan == sorted(urutan), f"urutan isi kartu tidak sesuai: {urutan}"
assert "repetisi" in contoh and "Istirahat" in contoh, "takaran tidak dirender"
inti = contoh.split('class="exercise-desc">')[1].split("</div>")[0].strip()
assert 0 < len(inti) <= 70, f"keterangan kartu terlalu panjang ({len(inti)}): {inti}"
print(f"   inti gerakan: {inti}")
at = tombol_detail[0].click().run()
assert not at.exception, [e.value for e in at.exception]
assert at.session_state["page"] == "Workout Tutorial", at.session_state["page"]
terpilih = at.session_state["selected_workout"]
assert terpilih and terpilih.get("tutorial"), "tutorial tidak ikut terpilih"

at2 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
at2.run()
for key, value in {**BASE_STATE, "page": "Workout Tutorial",
                   "selected_workout": terpilih}.items():
    at2.session_state[key] = value
at2.run()
if at2.exception:
    for e in at2.exception:
        print("   !! EXCEPTION:", e.value)
    raise AssertionError("halaman Workout Tutorial melempar exception")
langkah = [t.value for t in at2.markdown if "Langkah Pelaksanaan" in (t.value or "")]
assert langkah, "judul Langkah Pelaksanaan tidak dirender"
teks = [w.value for w in at2.get("markdown")]
baris_langkah = [t for t in teks if t and t.strip().startswith(("1.", "2.", "3."))]
print(f"   {len(baris_langkah)} baris langkah dirender, contoh:")
for t in baris_langkah[:3]:
    print("     ", t[:110])
assert any("Latihan " in (t or "") for t in teks), "keterangan Indonesia tidak dirender"

print("== Workout Tutorial (tanpa tutorial cocok) ==")
at3 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
at3.run()
tanpa = {"exercise": dict(terpilih["exercise"]), "tutorial": None}
for key, value in {**BASE_STATE, "page": "Workout Tutorial",
                   "selected_workout": tanpa}.items():
    at3.session_state[key] = value
at3.run()
if at3.exception:
    for e in at3.exception:
        print("   !! EXCEPTION:", e.value)
    raise AssertionError("halaman Workout Tutorial (tanpa tutorial) melempar exception")
assert any("Detail tutorial belum ditemukan" in (i.value or "") for i in at3.info)
print("   fallback tanpa tutorial OK")

print("== Halaman Masuk ==")
at = run_tamu("Login")
label_tombol = [b.label for b in at.button]
for wajib in ("Masuk", "Lupa Password?", "Daftar"):
    assert wajib in label_tombol, f"tombol '{wajib}' tidak ada: {label_tombol}"
kunci_tombol = {b.proto.id.split("-")[-1] if hasattr(b, "proto") else "" for b in at.button}
teks = " ".join(m.value or "" for m in at.markdown)
assert "Selamat Datang Kembali" in teks, "judul halaman masuk tidak dirender"
assert 'class="wajib"' in teks, "penanda wajib (*) tidak dirender"
assert "Belum punya akun?" in teks, "ajakan daftar tidak dirender"
# Ilustrasi hero: berkasnya harus benar-benar ada, karena render_hero memilih
# diam kalau tidak -- kolom kiri jadi kosong tanpa pesan kesalahan apa pun.
from src.views.auth import HERO_GAMBAR  # noqa: E402

for nama_halaman, berkas in HERO_GAMBAR.items():
    assert berkas.exists(), f"gambar hero {nama_halaman} tidak ada: {berkas}"
assert len(at.image) == 1, f"gambar hero tidak tunggal: {len(at.image)}"
print(f"   {len(at.text_input)} kotak isian, 1 gambar hero, tombol: {label_tombol}")

print("== Masuk: kredensial salah ditolak ==")
at.text_input(key="masuk_email").set_value(EMAIL).run()
at.text_input(key="masuk_sandi").set_value("sandi-salah").run()
at = at.button(key="tombol_masuk").click().run()
assert not at.exception, [e.value for e in at.exception]
assert any("salah" in (e.value or "").lower() for e in at.error), \
    f"tidak ada pesan gagal: {[e.value for e in at.error]}"
assert not at.session_state["authenticated"], "sandi salah tapi malah masuk"
print("   ditolak dengan benar")

print("== Masuk -> Daftar -> Masuk (navigasi tautan) ==")
at = run_tamu("Login")
at = at.button(key="ke_daftar").click().run()
assert not at.exception, [e.value for e in at.exception]
assert at.session_state["page"] == "Register", at.session_state["page"]
teks = " ".join(m.value or "" for m in at.markdown)
assert "Buat Akun Baru" in teks, "judul halaman daftar tidak dirender"
at = at.button(key="ke_masuk").click().run()
assert at.session_state["page"] == "Login", at.session_state["page"]
print("   bolak-balik masuk<->daftar OK")

print("== Masuk -> Lupa Password ==")
at = run_tamu("Login")
at = at.button(key="ke_lupa_sandi").click().run()
assert not at.exception, [e.value for e in at.exception]
assert at.session_state["page"] == "ForgotPassword", at.session_state["page"]
print("   pindah ke halaman lupa sandi OK")

print("== Halaman Daftar: pendaftaran akun baru ==")
at = run_tamu("Register")
# Empat kotak isian formulir daftar, berurutan sesuai tampilan. Diambil per
# indeks, bukan per key, karena key widget di dalam st.form dibuat otomatis
# oleh Streamlit dan bentuknya bisa berubah antar-versi.
assert len(at.text_input) == 4, f"jumlah kotak isian tak terduga: {len(at.text_input)}"
assert len(at.date_input) == 1, "st.date_input tanggal lahir hilang"
assert len(at.image) == 1, "ilustrasi hero halaman daftar tidak dirender"
at.text_input[0].set_value("Uji Coba")
at.text_input[1].set_value("uji.smoke@gmail.com")
at.text_input[2].set_value("RahasiaKuat1")
at.text_input[3].set_value("RahasiaKuat1")
at.checkbox[0].set_value(True)
kirim = [b for b in at.button if (b.label or "") == "Daftar"]
assert len(kirim) == 1, f"tombol kirim tidak tunggal: {[b.label for b in at.button]}"
at = kirim[0].click().run()
assert not at.exception, [e.value for e in at.exception]
kabar = [w.value for w in at.warning] + [s.value for s in at.success]
assert any("Akun" in (t or "") for t in kabar), \
    f"pendaftaran tidak memberi kabar apa pun: {kabar} / {[e.value for e in at.error]}"
print(f"   {kabar[0][:70]}...")

print("== Daftar: konfirmasi sandi tidak cocok ditolak ==")
at = run_tamu("Register")
at.text_input[0].set_value("Uji Dua")
at.text_input[1].set_value("uji.dua@gmail.com")
at.text_input[2].set_value("RahasiaKuat1")
at.text_input[3].set_value("BedaSekali2")
at.checkbox[0].set_value(True)
at = [b for b in at.button if (b.label or "") == "Daftar"][0].click().run()
assert any("tidak cocok" in (e.value or "") for e in at.error), \
    f"sandi beda tapi lolos: {[e.value for e in at.error]}"
print("   ditolak dengan benar")

print("== Ganti Latihan lewat UI ==")
at = run("Workout Recommendation", click="Buat Program Latihan")
sebelum_latihan = [str(t) for t in at.session_state["exercise_recommendations"]["Title"]]
tombol_ganti = [b for b in at.button if (b.label or "") == "Ganti Latihan"]
assert tombol_ganti, f"tombol Ganti Latihan tidak ada: {[b.label for b in at.button]}"
print(f"   {len(tombol_ganti)} tombol ganti tersedia")
at = tombol_ganti[0].click().run()
assert not at.exception, [e.value for e in at.exception]
sesudah_latihan = [str(t) for t in at.session_state["exercise_recommendations"]["Title"]]
berubah = [(a, b) for a, b in zip(sebelum_latihan, sesudah_latihan) if a != b]
assert berubah or any("pengganti" in (w.value or "") for w in at.warning), \
    f"klik Ganti Latihan tidak mengubah apa pun dan tidak memberi alasan\n{sebelum_latihan}\n{sesudah_latihan}"
if berubah:
    print(f"   {berubah[0][0][:40]} -> {berubah[0][1][:40]}")
else:
    print("   tidak ada pengganti relevan (diberitahukan lewat peringatan)")

print("== Tema: kotak isian putih bergaris tepi ==")
# Warna kotak isian datang dari tema Streamlit, BUKAN dari CSS di
# core/styles.py -- frontend memasangnya sebagai
# `backgroundColor: theme.colors.secondaryBg` pada kotak isian, dan garis
# tepinya sebagai `widgetBorderColor || transparent`. Nilai-nilai inilah yang
# menentukan tampilannya, jadi inilah yang diuji.
import streamlit as _st  # noqa: E402

assert _st.get_option("theme.secondaryBackgroundColor") == "#ffffff", \
    "latar kotak isian bukan putih -- rancangan meminta putih"
assert _st.get_option("theme.showWidgetBorder") is True, \
    "garis tepi kotak isian mati; tanpa itu kotak putih tidak terlihat di kartu putih"
assert _st.get_option("theme.borderColor") == "#e5e7eb", "warna garis tepi berubah"
assert _st.get_option("theme.primaryColor") == "#FF4646", "warna primary berubah"
# Blok kode & header tabel dulu mewarisi merah muda dari secondaryBackgroundColor;
# keduanya harus tetap punya warna sendiri setelah nilai itu jadi putih.
assert _st.get_option("theme.codeBackgroundColor") == "#fff7f7", "blok kode kehilangan warna"
print("   putih #ffffff + garis tepi #e5e7eb, primary #FF4646")

print("== Halaman lain tetap merender (widget ikut berubah warna) ==")
for _halaman in ("Profile", "Calorie Calculator"):
    _at = run(_halaman)
    print(f"   {_halaman}: OK")

print("\nSEMUA SMOKE TEST LOLOS")
