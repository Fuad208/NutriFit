"""Pemetaan istilah sistem ke label berbahasa Indonesia yang tampil di layar."""

from __future__ import annotations


ISTILAH_LATIHAN: dict[str, str] = {
    # --- Bagian tubuh: tabel exercises ---
    "abdominals": "Perut",
    "abductors": "Otot Abduktor",
    "adductors": "Otot Adduktor",
    "biceps": "Bisep",
    "calves": "Betis",
    "chest": "Dada",
    "forearms": "Lengan Bawah",
    "glutes": "Bokong",
    "hamstrings": "Paha Belakang",
    "lats": "Sayap (Latissimus)",
    "lower back": "Punggung Bawah",
    "middle back": "Punggung Tengah",
    "quadriceps": "Paha Depan",
    "shoulders": "Bahu",
    "traps": "Trapezius",
    "triceps": "Trisep",
    # --- Bagian tubuh tambahan: dataset tutorial ---
    "back": "Punggung",
    "cardio": "Kardio",
    "lower arms": "Lengan Bawah",
    "lower legs": "Tungkai Bawah",
    "neck": "Leher",
    "upper arms": "Lengan Atas",
    "upper legs": "Tungkai Atas",
    "waist": "Pinggang",
    # --- Alat: tabel exercises ---
    "bands": "Karet Resistensi",
    "barbell": "Barbel",
    "body only": "Tanpa Alat",
    "cable": "Kabel",
    "dumbbell": "Dumbel",
    "e-z curl bar": "Barbel EZ",
    "exercise ball": "Bola Senam",
    "foam roll": "Foam Roller",
    "kettlebells": "Kettlebell",
    "machine": "Mesin",
    "medicine ball": "Bola Medicine",
    "other": "Lainnya",
    # --- Alat tambahan: dataset tutorial ---
    "assisted": "Dengan Bantuan",
    "band": "Karet Resistensi",
    "body weight": "Berat Badan",
    "bosu ball": "Bola Bosu",
    "elliptical machine": "Mesin Eliptikal",
    "ez barbell": "Barbel EZ",
    "hammer": "Hammer",
    "kettlebell": "Kettlebell",
    "leverage machine": "Mesin Leverage",
    "olympic barbell": "Barbel Olimpiade",
    "resistance band": "Karet Resistensi",
    "roller": "Roller",
    "rope": "Tali",
    "skierg machine": "Mesin SkiErg",
    "sled machine": "Mesin Sled",
    "smith machine": "Mesin Smith",
    "stability ball": "Bola Stabilitas",
    "stationary bike": "Sepeda Statis",
    "stepmill machine": "Mesin Stepmill",
    "tire": "Ban",
    "trap bar": "Trap Bar",
    "upper body ergometer": "Ergometer Tubuh Atas",
    "weighted": "Dengan Beban",
    "wheel roller": "Roda Roller",
    # --- Level kesulitan ---
    "beginner": "Pemula",
    "intermediate": "Menengah",
    "expert": "Ahli",
    # --- Jenis latihan ---
    "olympic weightlifting": "Angkat Besi Olimpiade",
    "plyometrics": "Pliometrik",
    "powerlifting": "Powerlifting",
    "strength": "Kekuatan",
    "stretching": "Peregangan",
    "strongman": "Strongman",
    # --- Otot target: dataset tutorial ---
    "abs": "Perut",
    "cardiovascular system": "Sistem Kardiovaskular",
    "delts": "Deltoid (Bahu)",
    "levator scapulae": "Levator Skapula",
    "pectorals": "Dada (Pektoral)",
    "quads": "Paha Depan",
    "serratus anterior": "Seratus Anterior",
    "spine": "Tulang Belakang",
    "upper back": "Punggung Atas",
    # --- Otot sekunder: dataset tutorial ---
    "ankle stabilizers": "Stabilisator Pergelangan Kaki",
    "ankles": "Pergelangan Kaki",
    "brachialis": "Brakialis",
    "core": "Inti Tubuh",
    "deltoids": "Deltoid",
    "feet": "Telapak Kaki",
    "grip muscles": "Otot Genggaman",
    "groin": "Selangkangan",
    "hands": "Tangan",
    "hip flexors": "Fleksor Pinggul",
    "inner thighs": "Paha Dalam",
    "latissimus dorsi": "Latissimus Dorsi",
    "lower abs": "Perut Bawah",
    "obliques": "Otot Perut Samping",
    "rear deltoids": "Deltoid Belakang",
    "rhomboids": "Rhomboid",
    "rotator cuff": "Rotator Cuff",
    "shins": "Tulang Kering",
    "soleus": "Soleus",
    "sternocleidomastoid": "Sternokleidomastoid",
    "trapezius": "Trapezius",
    "upper chest": "Dada Atas",
    "wrist extensors": "Ekstensor Pergelangan Tangan",
    "wrist flexors": "Fleksor Pergelangan Tangan",
    "wrists": "Pergelangan Tangan",
}


# Nilai "Any" dipakai sebagai opsi filter, bukan istilah dari dataset.
SEMUA = "Semua"

# Tujuan kebugaran dipakai di beberapa halaman, jadi terjemahannya ditaruh di
# sini alih-alih diulang sebagai dict lokal di tiap view.
TUJUAN_KEBUGARAN = {
    "Lose Weight": "Menurunkan Berat",
    "Maintain Weight": "Menjaga Berat",
    "Gain Weight": "Menaikkan Berat",
}


def id_tujuan(value) -> str:
    """Terjemahkan tujuan kebugaran ke bahasa Indonesia."""
    return TUJUAN_KEBUGARAN.get(str(value or "").strip(), str(value or "-"))


def id_istilah(value) -> str:
    """Terjemahkan satu istilah latihan ke bahasa Indonesia.

    Istilah tak dikenal dikembalikan dalam Title Case, bukan string kosong,
    supaya penambahan data baru tidak membuat teksnya hilang dari layar.
    """
    if value is None:
        return "-"
    teks = str(value).strip()
    if not teks:
        return "-"
    if teks == SEMUA or teks.lower() == "any":
        return SEMUA
    return ISTILAH_LATIHAN.get(teks.lower(), teks.title())


def id_daftar(values) -> str:
    """Terjemahkan kumpulan istilah jadi satu kalimat dipisah koma."""
    if not values:
        return "-"
    return ", ".join(id_istilah(item) for item in values)


# Nama slot makan disimpan dalam bahasa Inggris di record rekomendasi menu
# (lihat MEAL_TEMPLATES di recommender.py). Petanya ditaruh di sini, bukan di
# views/meal.py, karena dashboard juga memakainya untuk feed aktivitas --
# dan views/meal.py mengimpor views/home.py, jadi arah impor sebaliknya akan
# melingkar.
SLOT_MAKAN = {
    "Breakfast": "Sarapan",
    "Lunch": "Makan Siang",
    "Snack": "Camilan",
    "Dinner": "Makan Malam",
}


def id_slot_makan(slot) -> str:
    """Terjemahkan nama slot makan; slot tak dikenal dikembalikan apa adanya."""
    teks = str(slot or "").strip()
    return SLOT_MAKAN.get(teks, teks or "-")
