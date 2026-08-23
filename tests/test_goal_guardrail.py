"""Uji pagar tujuan berbasis IMT: tujuan yang bertentangan dengan kondisi gizi tidak ditawarkan."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from _isolasi import pakai_schema_uji  # noqa: E402

pakai_schema_uji("pagar")

import pandas as pd  # noqa: E402
from src import recommender as R  # noqa: E402

R.check_image_urls_concurrently = lambda urls, max_workers=20: [True] * len(urls)
_members = pd.read_csv(ROOT / "data" / "gym_members.csv")
_foods = pd.read_csv(ROOT / "data" / "food_nutrition.csv")
_ex = pd.read_csv(ROOT / "data" / "training_program.csv").head(300)
R.load_dataset_tables = lambda: (_members, _foods, _ex)

from datetime import datetime  # noqa: E402
from uuid import uuid4  # noqa: E402

from src.database import CALORIE_STORE, append_record, ensure_database, save_users  # noqa: E402
from src.nutrition import calculate_nutrition_targets  # noqa: E402

ensure_database()
USER_ID, EMAIL = "pagar-user", "pagar@gmail.com"
nutrition = calculate_nutrition_targets(
    gender="Male", weight_kg=82.0, height_cm=168.0, age=30,
    activity_level="Medium", fitness_goal="Maintain Weight",
)
# Profil tersimpan sengaja BUKAN 70/175 -- untuk membuktikan nilai bawaan
# widget diambil dari riwayat, bukan dari angka yang dipatok di kode.
profile = {
    "gender": "Male", "age": 30, "weight_kg": 82.0, "height_cm": 168.0,
    "activity_level": "Medium", "experience_level": "Intermediate",
    "fitness_goal": "Maintain Weight", "bmi": nutrition.bmi, "user_cluster": 1,
}
save_users({EMAIL: {
    "user_id": USER_ID, "email": EMAIL, "name": "Pagar", "role": "user",
    "password_hash": "x", "auth_provider": "local", "email_verified": True,
    "gender": "Male", "birth_date": "1995-01-01",
    "profile": profile, "nutrition": nutrition.__dict__,
}})
append_record(CALORIE_STORE, {
    "id": str(uuid4()), "user_id": USER_ID, "email": EMAIL,
    "profile": profile, "nutrition": nutrition.__dict__,
    "created_at": datetime.now().isoformat(timespec="seconds"),
})

from streamlit.testing.v1 import AppTest  # noqa: E402

BASE = {"authenticated": True, "current_user": EMAIL,
        "nutrition": nutrition, "profile": profile}
lolos = gagal = 0


def cek(nama, syarat, keterangan=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  OK   {nama}")
    else:
        gagal += 1
        print(f"  GAGAL {nama} -- {keterangan}")


def buka(berat=None, tinggi=None):
    """Render halaman kalori, opsional dengan berat/tinggi yang diubah pengguna."""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
    at.run()
    for k, v in {**BASE, "page": "Calorie Calculator"}.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    if berat is not None:
        at.number_input[0].set_value(berat).run()
    if tinggi is not None:
        at.number_input[1].set_value(tinggi).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def teks(at):
    return " | ".join(
        [m.value for m in at.markdown] + [i.value for i in at.info]
        + [w.value for w in at.warning] + [e.value for e in at.error]
    )


print("=" * 92)
print("1. NILAI BAWAAN DIAMBIL DARI RIWAYAT, BUKAN 70/175")
print("=" * 92)
at = buka()
cek("berat bawaan = 82,0 (dari riwayat)", at.number_input[0].value == 82.0,
    f"dapat {at.number_input[0].value}")
cek("tinggi bawaan = 168,0 (dari riwayat)", at.number_input[1].value == 168.0,
    f"dapat {at.number_input[1].value}")
cek("batas minimum tinggi = 140", at.number_input[1].min == 140.0,
    f"dapat {at.number_input[1].min}")

print("\n" + "=" * 92)
print("2. BMI DAN RENTANG BERAT SEHAT TAMPIL SEBELUM PILIHAN TUJUAN")
print("=" * 92)
at = buka(berat=98.0, tinggi=172.0)
t = teks(at)
cek("kartu BMI menampilkan 33.1", "33.1" in t, t[:160])
cek("kategori Obesitas II tampil", "Obesitas II" in t, t[:160])
cek("rentang berat sehat 54.7 - 68.0 tampil", "54.7" in t and "68.0" in t, t[:200])

print("\n" + "=" * 92)
print("3. OBESITAS -> TUJUAN DITETAPKAN, RADIO TIDAK DIRENDER")
print("=" * 92)
for berat, tinggi, kat in [(98.0, 172.0, "Obesitas II"), (78.0, 172.0, "Obesitas I")]:
    at = buka(berat=berat, tinggi=tinggi)
    t = teks(at)
    cek(f"{kat}: radio Tujuan tidak ada", len(at.radio) == 0, f"ada {len(at.radio)} radio")
    cek(f"{kat}: pernyataan 'Tujuan ditetapkan' tampil", "ditetapkan" in t, t[:180])
    cek(f"{kat}: yang ditetapkan Menurunkan Berat", "Menurunkan Berat" in t, t[:180])
    cek(f"{kat}: tombol Hitung aktif", any(not b.disabled for b in at.button
                                           if "Hitung" in (b.label or "")))

print("\n" + "=" * 92)
print("4. KURUS -> MENURUNKAN BERAT MEMICU ERROR + KONFIRMASI")
print("=" * 92)
at = buka(berat=45.0, tinggi=172.0)
t = teks(at)
cek("Kurus: radio dirender dengan 3 pilihan", len(at.radio) == 1 and len(at.radio[0].options) == 3,
    f"{len(at.radio)} radio")
cek("Kurus: bawaan = Menaikkan Berat", at.radio[0].value == "Menaikkan Berat", at.radio[0].value)
cek("Kurus: bawaan tidak memunculkan error", len(at.error) == 0, [e.value for e in at.error])

at.radio[0].set_value("Menurunkan Berat").run()
t = teks(at)
cek("Kurus + Menurunkan: st.error muncul", len(at.error) == 1, [e.value for e in at.error])
cek("Kurus + Menurunkan: pesan menyebut tidak disarankan",
    any("tidak disarankan" in (e.value or "") for e in at.error), [e.value for e in at.error])
cek("Kurus + Menurunkan: kotak konfirmasi muncul", len(at.checkbox) >= 1, f"{len(at.checkbox)}")
tombol = [b for b in at.button if "Hitung" in (b.label or "")]
cek("Kurus + Menurunkan: tombol Hitung NONAKTIF", tombol and tombol[0].disabled,
    f"disabled={tombol[0].disabled if tombol else 'tidak ada tombol'}")

at.checkbox[0].set_value(True).run()
tombol = [b for b in at.button if "Hitung" in (b.label or "")]
cek("setelah konfirmasi: tombol Hitung AKTIF", tombol and not tombol[0].disabled,
    f"disabled={tombol[0].disabled if tombol else 'tidak ada tombol'}")

print("\n" + "=" * 92)
print("5. GEMUK -> MENJAGA memberi warning, MENAIKKAN memberi error")
print("=" * 92)
at = buka(berat=70.0, tinggi=172.0)
cek("Gemuk: bawaan = Menurunkan Berat", at.radio[0].value == "Menurunkan Berat", at.radio[0].value)
at.radio[0].set_value("Menjaga Berat").run()
cek("Gemuk + Menjaga: st.warning muncul", len(at.warning) == 1, [w.value for w in at.warning])
cek("Gemuk + Menjaga: tombol tetap aktif",
    not [b for b in at.button if "Hitung" in (b.label or "")][0].disabled)
at.radio[0].set_value("Menaikkan Berat").run()
cek("Gemuk + Menaikkan: st.error muncul", len(at.error) == 1, [e.value for e in at.error])
cek("Gemuk + Menaikkan: tombol nonaktif sebelum konfirmasi",
    [b for b in at.button if "Hitung" in (b.label or "")][0].disabled)

print("\n" + "=" * 92)
print("6. NORMAL -> KETIGANYA BOLEH, DUA DISERTAI BATAS")
print("=" * 92)
at = buka(berat=66.0, tinggi=172.0)
cek("Normal: bawaan = Menjaga Berat", at.radio[0].value == "Menjaga Berat", at.radio[0].value)
cek("Normal + Menjaga: tanpa peringatan apa pun",
    len(at.error) == 0 and len(at.warning) == 0, teks(at)[:150])
at.radio[0].set_value("Menurunkan Berat").run()
t = teks(at)
cek("Normal + Menurunkan: keterangan batas bawah 54.7 tampil", "54.7" in t, t[:220])
cek("Normal + Menurunkan: tombol tetap aktif",
    not [b for b in at.button if "Hitung" in (b.label or "")][0].disabled)
at.radio[0].set_value("Menaikkan Berat").run()
t = teks(at)
cek("Normal + Menaikkan: keterangan batas atas 68.0 tampil", "68.0" in t, t[:220])

print("\n" + "=" * 92)
print("7. PERHITUNGAN MASIH BERJALAN SETELAH FORM DIBONGKAR")
print("=" * 92)
at = buka(berat=98.0, tinggi=172.0)
tombol = [b for b in at.button if "Hitung" in (b.label or "")][0]
tombol.click().run()
cek("klik Hitung tidak melempar exception", not at.exception, [e.value for e in at.exception])
prof = dict(at.session_state["profile"] or {})
cek("profil tersimpan memakai tujuan yang ditetapkan",
    prof.get("fitness_goal") == "Lose Weight", prof.get("fitness_goal"))
cek("berat tersimpan = 98.0", prof.get("weight_kg") == 98.0, prof.get("weight_kg"))
cek("target kalori = defisit (bukan surplus)",
    at.session_state["nutrition"].target_calories < at.session_state["nutrition"].tdee,
    f"target {at.session_state['nutrition'].target_calories} vs TDEE {at.session_state['nutrition'].tdee}")

print("\n" + "=" * 92)
print(f"HASIL: {lolos} lolos, {gagal} gagal")
print("=" * 92)
sys.exit(1 if gagal else 0)
