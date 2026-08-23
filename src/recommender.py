from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import lru_cache
from http.client import HTTPException
import json
import os
import re
import time
from typing import Iterable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "4")

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import calinski_harabasz_score, silhouette_score
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import MinMaxScaler

from .database import SQLStore
from .nutrition import NutritionResult
from .paths import DATA_DIR


# Proporsi kuota kalori tiap slot waktu makan. Jumlahnya persis 1,0 sehingga
# total kuota keempat slot selalu sama dengan kebutuhan energi harian pengguna.
MEAL_DISTRIBUTION = {
    "Breakfast": 0.25,
    "Lunch": 0.30,
    "Snack": 0.20,
    "Dinner": 0.25,
}

# Susunan peran gizi tiap slot, satu template per tujuan kebugaran. Peran gizi
# berasal dari K-Means makanan: A tinggi karbohidrat, B protein ramping,
# C rendah kalori, D protein berlemak. Panjang daftar = jumlah item pada slot
# itu, dan kuota slot dibagi rata ke tiap item.
# Alasan pemilihan tiap template: docs/catatan-desain.md bagian 7.
MEAL_TEMPLATES = {
    # Menurunkan berat: satu-satunya slot karbohidrat ada di makan siang, dan
    # peran D tidak dipakai sama sekali.
    "Lose Weight": {
        "Breakfast": ["B", "C"],
        "Lunch": ["A", "B", "C"],
        "Snack": ["C"],
        "Dinner": ["B", "C"],
    },
    # Menjaga berat: satu slot karbohidrat di sarapan dan makan siang.
    "Maintain Weight": {
        "Breakfast": ["A", "B"],
        "Lunch": ["A", "B", "C"],
        "Snack": ["C"],
        "Dinner": ["B", "C"],
    },
    # Menaikkan berat: karbohidrat di setiap waktu makan, satu slot protein
    # berlemak, dan satu slot rendah kalori dipertahankan di makan malam.
    "Gain Weight": {
        "Breakfast": ["A", "B"],
        "Lunch": ["A", "B", "D"],
        "Snack": ["A"],
        "Dinner": ["A", "C"],
    },
}

# Tujuan yang dipakai bila profil pengguna tidak memuat tujuan yang dikenali --
# record lama, atau pemanggilan dari notebook yang tidak mengoper tujuan.
DEFAULT_FITNESS_GOAL = "Maintain Weight"

SNACK_SLOT = "Snack"
BREAKFAST_SLOT = "Breakfast"

# Slot makan berat. Ketiganya memakai pagar yang sama: kudapan manis dan
# jajanan yang selalu berstatus camilan tidak boleh mengisi salah satunya.
MAIN_MEAL_SLOTS = ("Breakfast", "Lunch", "Dinner")


def meal_template(fitness_goal: str | None = None) -> dict[str, list[str]]:
    """Susunan peran gizi tiap slot untuk satu tujuan kebugaran.

    Camilan selalu satu item pada ketiga tujuan.
    """
    goal = normalize_goal(fitness_goal) if fitness_goal else DEFAULT_FITNESS_GOAL
    return MEAL_TEMPLATES.get(goal, MEAL_TEMPLATES[DEFAULT_FITNESS_GOAL])

# Makanan pokok sumber karbohidrat utama. Dipakai is_staple_food() untuk
# membatasi satu makanan pokok per slot.
STAPLE_PATTERN = (
    r"^nasi\b|\bnasi\b|^bubur\b|\bbubur\b|^lontong\b|\bketupat\b|^ketupat\b"
    r"|^mie\b|^mi\b|\bmie\b|^bihun\b|\bbihun\b|^kwetiau\b|^misoa\b|^makaroni\b"
    r"|^spaghetti\b|^vermicelli\b|^soun\b|^papeda\b|^tiwul\b|^oyek\b|^jagung titi\b"
    r"|^roti\b|^lontong\b|^buras\b|^bacang\b|^lemper\b|^pulut\b|^ketan\b|^lopis\b"
    r"|^rasbi\b|^rasi\b|^kapurung\b|^intip\b"
)

# Bentuk sajian yang tidak pantas jadi menu sarapan: gula-gula, jajanan manis
# pekat, dan gorengan kering berbasis kerupuk.
BREAKFAST_UNSUITABLE_PATTERN = (
    r"^permen\b|\bdodol\b|^jenang\b|^wajik\b|^wajit\b|^geplak\b|^yangko\b"
    r"|\bes krim\b|^es mambo\b|^es sirup\b|^coklat\b|^choklat\b|\bcoklat batang\b"
    # Tidak di-anchor ke awal nama: bentuknya sering muncul di belakang, mis.
    # "Kacang Tanah rempeyek" dan "Emping (kerupuk melinjo)".
    r"|\bkerupuk\b|\bkrupuk\b|\bkeripik\b|\bkripik\b|\bemping\b|\brempeyek\b|^brondong\b"
    r"|^noga\b|^enting-enting\b|^widaran\b|^suwir-suwir\b|^sale\b|^kwaci\b"
    r"|^manisan\b|^selai\b|^jam selai\b|^koya\b|^biskuit\b|^slondok\b|^rengginang\b"
)

# Kudapan manis dan jajanan pasar: bentuk sajian yang tidak pernah menjadi
# komponen makan berat. Digabung ke MAIN_MEAL_UNSUITABLE_PATTERN di bawah.
# Latar masalahnya: docs/catatan-desain.md bagian 8.
DESSERT_PATTERN = (
    r"\bkue\b|\bbolu\b|\bbrownies\b|\bklepon\b|\bonde-onde\b|\bonde onde\b"
    r"|\bnagasari\b|\bcucur\b|\bserabi\b|\bsurabi\b|\bapem\b|\bbikang\b"
    r"|\blupis\b|\bwingko\b|\bbakpia\b|\bdonat\b|\bpuding\b|\bpudding\b"
    r"|\bcendol\b|\bkolak\b|\bbubur sumsum\b|\blapis legit\b|\bceriping\b"
    r"|\bcarabikang\b|\bkembang goyang\b|\bbolang-baling\b|\bmoci\b|\bmochi\b"
)

# Batas Volumetric Sanity Check: gramasi hasil konversi kalori harus berada di
# rentang ini. Item yang gagal didiskualifikasi oleh _pick_food_candidate().
MIN_PORTION_GRAM = 50
MAX_PORTION_GRAM = 450

# --------------------------------------------------------------------------- #
# Penetapan jumlah klaster
# --------------------------------------------------------------------------- #
# Rentang kandidat K yang disapu Metode Siku. Metode Siku dipakai SENDIRIAN
# untuk memilih K; metrik mutu dihitung sesudahnya di fungsi *_performance
# sebagai penilaian, bukan sebagai pemilih.
CLUSTER_SEARCH_RANGE = range(2, 11)

# Ambang jumlah baris sebelum metrik berbasis matriks jarak beralih ke sampel
# deterministik, supaya kebutuhan memorinya tidak tumbuh kuadratik.
EVALUATION_SAMPLE_LIMIT = 2000

# Fitur K-Means makanan: empat makronutrien ditambah kepadatan protein, yaitu
# satu-satunya sumbu yang memisahkan protein ramping dari protein berlemak.
# Lihat docs/catatan-desain.md bagian 1.
FOOD_MACRO_COLUMNS = ["calories", "proteins", "fat", "carbohydrate"]
FOOD_PROTEIN_DENSITY_COLUMN = "Protein_Density"

# Jumlah klaster K-Means, ditetapkan tetap karena MEAL_TEMPLATES membutuhkan
# empat peran gizi yang bisa diminta per slot. Kurva Metode Siku dan
# perbandingan metriknya: docs/catatan-desain.md bagian 1.
FOOD_CLUSTER_COUNT = 4

# Batas jumlah menu dari satu keluarga hidangan yang boleh menumpuk di peringkat
# atas. Keluarga hidangan = dua kata pertama nama menu (lihat dish_family()).
# Pengukuran dampaknya: docs/catatan-desain.md bagian 6.
DISH_FAMILY_LIMIT = 2

# Banyaknya titik awal yang diadu sebelum sebuah klaster ditetapkan. Inisialisasi
# linspace selalu ikut diadu, ditambah seed 0..N-1, sehingga hasilnya tetap
# deterministik. Pemenangnya dipilih dengan fungsi biaya algoritmanya sendiri.
EXERCISE_INIT_ATTEMPTS = 10
MEMBER_INIT_ATTEMPTS = 20

# --------------------------------------------------------------------------- #
# Atribut anggota dan pembobotannya
# --------------------------------------------------------------------------- #
# Dipakai bersama oleh pelatihan klaster, penilaian performa, dan pemetaan
# pengguna baru. Urutan kolom kategorikal menentukan urutan bobot di bawah.
MEMBER_NUMERIC_COLUMNS = ["Age", "Weight (kg)", "Height (m)", "BMI"]
MEMBER_CATEGORICAL_COLUMNS = ["Gender", "Activity_Level", "Experience_Label", "Fitness_Goal"]

# Bobot tiap atribut kategorikal pada jarak K-Prototypes. Tanpa pembobotan,
# klaster terbentuk oleh Gender sedangkan Fitness_Goal yang menjadi sasaran
# segmentasi justru tenggelam. Sapuan bobot dan harganya:
# docs/catatan-desain.md bagian 2.
MEMBER_CATEGORICAL_WEIGHTS = {"Fitness_Goal": 3.0}

# --------------------------------------------------------------------------- #
# Kelayakan menu
# --------------------------------------------------------------------------- #
# Kelayakan ditentukan DAFTAR TOLAK: sebuah menu diterima kecuali namanya
# menunjukkan ia bukan hidangan siap santap. Pola-pola di bawah dipakai
# filter_recommendable_foods(). Lihat docs/catatan-desain.md bagian 14.

# 1. BUKAN PANGAN MANUSIA. Ini soal keamanan, bukan selera, dan tidak boleh
#    dilonggarkan lewat filter kategori mana pun.
NOT_HUMAN_FOOD_PATTERN = (
    # Beracun: bongkrek (asam bongkrek), gadung dan picung (sianida).
    r"\bbongkrek\b|\bgadung\b|\bgadeng\b|\bpicung\b"
    # Pakan ternak & ampas industri.
    r"|\bbungkil\b|\bampas\b|\bdedak\b|\bkatul\b|\bkathul\b|\bonggok\b|\bpollard\b"
    # Minuman beralkohol.
    r"|^bir\b|\bbir \(|\bbrem\b|\btuak\b|\barak\b|\balkohol\b|\bciu\b"
    # Obat, jamu, dan sediaan medis.
    r"|\bjamu\b|\boralit\b|sirup (?:batuk|obat)|\bparasetamol\b|\bpapasetamol\b"
    # Susu formula & ASI.
    r"|breastmilk|\basi\b|susu formula"
    # Organ dengan bahaya kesehatan nyata: otak sangat tinggi kolesterol,
    # ginjal menumpuk logam berat dan purin.
    r"|^otak\b|\botak masakan\b|\bginjal\b"
    # Sarang burung walet: tonik mewah, bukan komponen makan harian.
    r"|^sarang burung"
)

# 2. NON-HALAL DAN SATWA DILINDUNGI. Disaring karena konteks pemakaian aplikasi
#    dan status perlindungan satwanya, bukan karena nilai gizinya.
PROTECTED_OR_HARAM_DISH_PATTERN = (
    r"^ham$|\bleverwost\b|\bsosis hati\b|\btinoransak\b"
    r"|\bkura-kura\b|\bpunai\b|\btelur burung sawah\b|\bbelida\b"
)

# 3. PROTEIN DIAWETKAN GARAM. Kadar natriumnya terlalu tinggi untuk dipakai
#    sebagai lauk utama sepiring makan, walaupun proteinnya tinggi.
SALT_CURED_PROTEIN_PATTERN = (
    # Ikan/telur yang digarami. Ditulis sebagai pasangan kata supaya "asin"
    # sebagai penanda rasa tidak ikut tertangkap.
    r"\bikan\b.*\basin\b|\basin\b.*\bikan\b|\btelur\b.*\basin\b"
    # Ikan teri kering, dendeng, jambal, dan peda -- semuanya diawetkan garam.
    r"|\bteri\b|\bdendeng\b|\bjambal\b|\bpeda\b"
)

# 4. BAHAN, BUMBU, DAN OLAHAN SETENGAH JADI. Bukan hidangan siap santap.
INGREDIENT_PATTERN = (
    r"\bmentah\b|\bkering\b|\bbibit\b"
    # Tepung, pati, serealia, beras.
    r"|\btepung\b|^pati\b|\bmaizena\b|\bhunkwe\b|\bsagu\b|\bterigu\b|^beras\b|^gabah"
    r"|^menir|^ketan\b|^jagung pipil|^biji\b|\bgaplek\b|^tiwul$|^sorgum$|^cantel$"
    # Bumbu, rempah, penyedap.
    r"|^bumbu|\bmerica\b|\bketumbar\b|\bkunyit\b|\blaos\b|\blengkuas\b|\bjahe\b"
    r"|\bkencur\b|\bsereh\b|\bserai\b|\bpandan\b|^salam$|\bkayu manis\b|^pala\b"
    r"|\bcengkeh\b|\bkemiri\b|\bandaliman\b|\bkapulaga\b|\bterasi\b|\bvetsin\b"
    r"|^garam|^kecap|^saos|^sambal$|\bcuka\b|\bragi\b|\bboros\b|\bpenyedap\b"
    # Minyak, lemak, gula, pemanis.
    r"|^minyak|\blemak\b|\bgajih\b|\bmentega\b|\bmargarin\b|\bkethak\b|^santan"
    r"|^gula|^madu$|\bsakarin\b|^sirup|^tebu$"
    # Bagian tanaman yang dipakai sebagai bahan.
    r"|^daun\b|^akar\b|^batang\b|^kembang\b|^bunga\b|^pucuk\b|^kulit\b|^bonggol\b"
    r"|^tunas\b|^rebung\b|^umbut\b|^klika\b|\bjeroan\b|\bdarah\b"
    # Sayur mentah sebagai bahan.
    r"|^bawang\b|^cabe\b|^cabai\b|^tomat\b|^wortel$|^kentang$|^buncis$|^bengkuang$"
    r"|^ketimun$|^mentimun$|^labu\b|^waluh\b|^terong$|^terung$|^lobak$|^sawi\b"
    r"|^selada\b|^kangkung$|^bayam\b|^kol$|^kubis$|^paria$|^pare\b|^jamur\b"
    r"|^toge$|^taoge$|^tauge$|^asparagus\b|^seledri$"
    # Susu dan telur mentah sebagai bahan.
    r"|^susu\b|^telur (?:ayam|itik|bebek|puyuh|burung|merpati|menthok)$"
    r"|^telur (?:ikan|.*bagian)\b"
    # Daging & ikan tanpa penanda olahan apa pun.
    r"|^daging\b|^ikan [a-z-]+$|^udang [a-z]*$|^cumi[- ]cumi$|^kerang$|^kepiting\b"
    r"|^ayam$|^bebek\b|^angsa$|^itik\b|^sapi\b|^kambing\b|^kerbau\b|^babat$"
    r"|^usus\b|^hati\b|^otak\b|^limfa\b|^dideh\b|^rempelo\b|^ati\b|^iso\b"
    r"|^kikil\b|^rambak\b|^tetelan\b|^jantung (?:ayam|itik|sapi|menthok|merpati)"
    # Kacang & umbi tanpa olahan.
    r"|^kacang [a-z]+$|^kedele\b|^kedelai\b|^koro\b|^gude$|^jengkol$|^petai$|^pete$"
    r"|^ubi\b|^singkong$|^talas$|^gembili\b|^ganyong$|^suweg$|^uwi$|^kimpul\b"
    r"|^senthe$|^kelapa\b"
)

# 3. Buah yang dipakai sebagai BAHAN, bukan dimakan sebagai buah. Buah segar
#    lainnya sengaja DITERIMA -- untuk aplikasi gizi, buah justru camilan yang
#    paling pantas direkomendasikan.
FRUIT_AS_INGREDIENT_PATTERN = (
    r"^nangka biji$|^biji nangka$|^nangka muda$|^gori\b"
    r"|^melinjo\b|^kulit melinjo$|^kolang[- ]kaling$|^jantung pisang"
    # Bentuk olahan buah yang dipakai sebagai bahan, bukan disantap sebagai buah.
    r"|\bbiji jambu monyet\b|\bkacang mete\b|\bkacang mede\b"
)

# Ambang kewajaran nilai gizi, dipakai nutrition_is_plausible(): massa makro tidak
# boleh melebihi 100 g per 100 g bahan, dan energi tercatat harus mendekati hasil
# hitung faktor Atwater.
NUTRITION_MASS_LIMIT_GRAM = 100
NUTRITION_ENERGY_TOLERANCE = 0.25

# 5. DIKECUALIKAN LEWAT DAFTAR KHUSUS. Minuman, pemanis, dan serealia mentah yang
#    lolos pola lain tetapi tetap bukan pengisi slot makan.
EXCLUDED_FOOD_PATTERN = (
    r"(?:(?<!kacang )\b(?:babi|khinzir|celeng|bagong|b2)\b"
    r"|\b(?:anjing|rw|penyu|tuntong|labi-labi|biawak|kelelawar|paniki|kalong|"
    r"codot|tikus|katak|kodok|bekicot)\b)"
)

# --------------------------------------------------------------------------- #
# Kelayakan camilan
# --------------------------------------------------------------------------- #
# Dinilai dari BENTUK SAJIAN, bukan jumlah kalorinya: sepiring nasi tetap makanan
# berat walaupun porsinya dipotong. Dipakai snack_eligibility().

# Bentuk sajian yang selalu camilan, apa pun kata lain di namanya. Dipakai
# lebih dulu supaya "kerupuk mie kuning goreng" tidak tertolak oleh kata "mie".
SNACK_ALWAYS_PATTERN = (
    r"\b(?:kerupuk|keripik|kripik|rempeyek|peyek|emping|getuk|kecimpring|renggi|intip)\b"
)

# Gabungan pagar untuk slot makan berat (sarapan, makan siang, makan malam).
# SNACK_ALWAYS_PATTERN ikut karena isinya memang selalu berstatus camilan.
MAIN_MEAL_UNSUITABLE_PATTERN = (
    BREAKFAST_UNSUITABLE_PATTERN + r"|" + DESSERT_PATTERN + r"|" + SNACK_ALWAYS_PATTERN
)

# Buah yang dimakan sebagai buah. Dipakai dua kali: sebagai kategori filter
# ("Buah") dan sebagai penanda kelayakan camilan.
FRUIT_PATTERN = (
    r"\b(?:alpukat|alpokat|anggur|apel|arbei|belimbing|cempedak|cerme|duku|durian|"
    r"duwet|jambu|jeruk|kedondong|kelengkeng|kepel|kesemek|kokosan|kurma|langsat|"
    r"mangga|manggis|markisa|melon|menteng|nanas|nangka|pepaya|rambutan|salak|sawo|"
    r"semangka|sirsak|srikaya|sukun|talok|kersen|cimplukan|matuwa|jambu biji|"
    r"buah naga|buah nona|buah merah|strawberry|stroberi|alpuket|"
    # Buah daerah bernama "Buah ...", ditulis spesifik karena kata "buah" polos
    # akan ikut menyeret sayuran seperti Buah kelor dan Kecipir buah muda.
    r"atung|kelenting|rukam|ruruhi|tuppa|"
    r"buah kom|buah negri|buah rotan)\b"
)

# Penanda bahan mentah yang HANYA berlaku kalau bukan buah: "segar" menandai
# bahan mentah pada "Sapi daging gemuk segar", tetapi menandai bentuk siap santap
# pada "Mangga segar". Lihat docs/catatan-desain.md bagian 14.
RAW_FRESH_PATTERN = r"\bsegar\b"

# 6. BUKAN SATU HIDANGAN UTUH. Minuman, pemanis, dan serealia yang wajib ditanak
#    dulu. Daftarnya disusun dari penyisiran seluruh nama menu lalu diadu dengan
#    pembantah adversarial (docs/catatan-desain.md bagian 14).
NOT_A_MEAL_PATTERN = (
    r"^es sirup$|^lemonade$|\bsquash\b|\bsquasih\b|^setrup\b|^kopi\b|^melase$"
    r"|^jali$|^jawawut$"
    r"|^jagung (?:kuning|putih) giling$|^jagung (?:kuning|putih) pipil lama$"
    # Bumbu dan pasta penyedap yang tidak disantap sendirian.
    r"|^petis\b|^taoco\b|^tauco\b|^tauji\b|^prey\b|^kepala susu\b|^asam masak\b"
    # Bahan yang dipakai sebagai pelengkap, bukan sebagai hidangan.
    r"|^kluwek\b|^peterseli\b|^kucai\b|^wijen$|^kenari$|^gelatine?$|^coklat bubuk$"
    # Daun dan sayuran yang tidak lazim disajikan sebagai hidangan mandiri.
    r"|^jotang\b|^krokot\b|^kerokot\b|^tespong\b|^susupan\b|^tekokak\b|^leunca\b"
    r"|^karawila\b|^rimbang\b|^putri malu\b|^purundawa\b|^andewi\b|^baligo\b|^erbis\b"
    # Anchor ke SELURUH nama (atau nama + kurung penjelas), bukan sekadar kata
    # pertama: "Paria Putih kukus", "Gambas lodeh", dan "Parede baleh masakan"
    # adalah hidangan matang dan harus tetap lolos.
    r"|^kundur$|^paria$|^paria \(|^pe-?cay$|^terung panjang$|^pepaya muda$"
    r"|^mostarda\b|^kool\b|^gambas$|^gambas \(|^kentang hitam$|^bit$"
)

# Buah yang tetap diterima walaupun namanya memuat "segar". Bentuk NON-buah dari
# tanaman yang sama tetap gugur karena masih tertangkap aturan lain.
FRESH_FRUIT_PATTERN = (
    FRUIT_PATTERN
    + r"|\b(?:pisang|lemon|matoa|lontar|siwalan|kawista|kranji|biwah|papaya)\b"
    + r"|\bterung belanda\b|^buah\s"
)

# Bentuk sajian yang lazim dimakan sebagai camilan bila tidak digabung dengan
# hidangan utama (mis. "ubi jalar rebus" camilan, tapi "ubi jalar sayur" lauk).
SNACK_FORM_PATTERN = (
    r"\b(?:gendar|pisang|kacang|jagung|ubi|singkong|talas|tales|ganyong|suweg|"
    r"belitung|bentul|batatas|gembili|ketela|tahu|tempe|oncom|telur|siomay|batagor|"
    r"pempek|nugget|perkedel|dadar)\b"
    # Buah segar ikut dianggap layak mengisi slot camilan.
    r"|" + FRESH_FRUIT_PATTERN
)

# Penanda hidangan utama/lauk: makanan pokok, masakan berkuah, dan olahan yang
# disantap bersama nasi. Semua ini didiskualifikasi dari slot camilan.
NOT_SNACK_PATTERN = (
    r"\b(?:nasi|mie|mi|bihun|kwetiau|bubur|lontong|ketupat|pundut|tim|soto|sop|sup|rawon|"
    r"gulai|kari|opor|semur|rendang|gudeg|coto|sate|bakso|rujak|ketoprak|gado-gado|gado|"
    r"pecel|karedok|urap|asinan|masakan|lawar|lawara|sukiyaki|bulgogi|teriyaki|yakiniku|"
    r"empal|dendeng|abon|paru|kikil|buntut|konro|iga|sayur|tumis|pepes|botok|balado|"
    r"oseng|kalio)\b"
)


# --------------------------------------------------------------------------- #
# Kategori bahan utama
# --------------------------------------------------------------------------- #
# Label -> (pola yang harus cocok, pola yang harus TIDAK cocok). Pola kedua
# memisahkan bahan yang namanya bertumpuk, mis. "telur ayam dadar" adalah telur.
# Dipakai food_category_mask(), yang sekaligus menjadi acuan relevansi pengujian.
FOOD_CATEGORIES: dict[str, tuple[str, str | None]] = {
    "Ayam": (r"\bayam\b", r"\btelur\b"),
    "Ikan & Seafood": (
        r"\b(?:ikan|bandeng|lele|mujair|mujahir|teri|tenggiri|gurame|patin|baung|belida|"
        r"papuyu|lais|jambal|belut|cumi|udang|kerang|tiram|kepiting|pindang|tongkol|bawal|"
        r"kakap|sarden|pempek|siomay|batagor|betok|keumamah|jukku|gete|sepi|pallu)\b",
        None,
    ),
    "Daging Sapi": (
        r"\b(?:sapi|beef|empal|dendeng|rendang|bulgogi|rawon|sukiyaki|tedong|konro|buntut|"
        r"kikil|tunjang|paru|yakiniku|teriyaki|naan|coto)\b",
        None,
    ),
    "Daging Kambing": (r"\b(?:kambing|domba)\b", None),
    # Kata "dadar" sengaja tidak ikut: keempat hidangan telur dadar di dataset
    # sudah memuat kata "telur", sedangkan "kue dadar gulung" bukan telur.
    "Telur": (r"\btelur\b", None),
    "Tahu, Tempe & Oncom": (r"\b(?:tahu|tempe|oncom)\b", None),
    "Sayuran": (
        r"\b(?:sayur|sayuran|bayam|kangkung|buncis|wortel|terong|terung|taoge|toge|selada|"
        r"paria|cap cai|karedok|gado-gado|gado|urap|pecel|asinan|ketoprak|pakis|kool|lebui|"
        # "kelor" ada di sini, BUKAN di FRUIT_PATTERN: "Buah kelor" adalah polong
        # kelor yang dimasak sebagai sayur, meski namanya diawali kata "buah".
        r"terubuk|umbut|kohu-kohu|ndusuk|garu|anyang|ares|kaparende|lamtoro|jengkol|kelor)\b",
        None,
    ),
    "Kacang-kacangan": (r"\bkacang\b", None),
    "Nasi & Olahan Beras": (
        # "beras" ikut supaya olahan beras yang namanya tidak memuat "nasi" tetap
        # terjangkau. Bahan mentah sudah tersaring lebih dulu di prepare_foods().
        r"\b(?:nasi|beras|bubur|lontong|intip|gendar|tim|pundut|ketupat|renggi)\b",
        None,
    ),
    "Mie & Bihun": (r"\b(?:mie|mi|bihun|kwetiau|pangsit|golosor)\b", None),
    "Umbi & Singkong": (
        r"\b(?:ubi|singkong|talas|tales|ganyong|gadung|suweg|kentang|belitung|bentul|"
        r"batatas|gembili|getuk|kecimpring|ketela)\b",
        None,
    ),
    "Jagung": (r"\bjagung\b", None),
    "Kerupuk & Keripik": (r"\b(?:kerupuk|keripik|kripik|rempeyek|peyek|emping)\b", None),
    "Pisang & Olahannya": (r"\bpisang\b", None),
    # Diletakkan PALING AKHIR supaya olahan yang memakai buah tetap masuk
    # kategori olahannya: "pisang goreng" tetap Pisang & Olahannya, bukan Buah.
    "Buah": (FRUIT_PATTERN, None),
}

# Bucket penampung supaya SETIAP baris dataset tetap bisa dijangkau lewat filter
# (dataset memuat banyak masakan daerah yang namanya tidak menyebut bahannya,
# mis. "tinoransak masakan").
OTHER_CATEGORY = "Lainnya"

# Pilihan preferensi sumber protein yang ditawarkan ke pengguna.
# Kunci = label yang tampil, nilai = satu atau lebih nama kategori di FOOD_CATEGORIES.
PROTEIN_PREFERENCE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "Ayam": ("Ayam",),
    # Sapi dan kambing digabung: peran gizinya sama, dan "Daging Kambing"
    # sendirian hanya punya satu menu sehingga tidak pernah bisa mengisi 8 slot.
    "Olahan Daging": ("Daging Sapi", "Daging Kambing"),
    "Telur": ("Telur",),
    "Ikan & Seafood": ("Ikan & Seafood",),
    "Olahan Kedelai": ("Tahu, Tempe & Oncom",),
    "Kacang-kacangan": ("Kacang-kacangan",),
    "Sayur": ("Sayuran",),
}

# Pilihan preferensi sumber karbohidrat, dipilih terpisah dari sumber protein.
# Peran gizi menentukan berapa banyak karbohidrat yang masuk, bukan yang mana.
CARB_PREFERENCE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "Nasi & Olahan Beras": ("Nasi & Olahan Beras",),
    "Mie & Bihun": ("Mie & Bihun",),
    "Umbi & Singkong": ("Umbi & Singkong",),
    "Jagung": ("Jagung",),
    "Pisang & Olahannya": ("Pisang & Olahannya",),
    "Buah": ("Buah",),
}


def _preference_options(
    daftar: dict[str, tuple[str, ...]],
    foods: pd.DataFrame,
    meal_slot: str | None = None,
) -> dict[str, tuple[str, ...]]:
    """Saring daftar preferensi ke yang benar-benar punya menu.

    Sebuah label ditawarkan bila SETIDAKNYA SATU kategori di baliknya punya isi.
    Kategori yang kosong dibuang dari tuple-nya, jadi "Olahan Daging" tetap
    tampil selama salah satu dari sapi atau kambing masih ada isinya.
    """
    tersedia = set(available_food_categories(foods, meal_slot=meal_slot))
    hasil: dict[str, tuple[str, ...]] = {}
    for label, kategori in daftar.items():
        ada = tuple(k for k in kategori if k in tersedia)
        if ada:
            hasil[label] = ada
    return hasil


def protein_preference_options(
    foods: pd.DataFrame, meal_slot: str | None = None
) -> dict[str, tuple[str, ...]]:
    """Label sumber protein yang benar-benar punya menu di dataset (atau di slot itu)."""
    return _preference_options(PROTEIN_PREFERENCE_CATEGORIES, foods, meal_slot)


def carb_preference_options(
    foods: pd.DataFrame, meal_slot: str | None = None
) -> dict[str, tuple[str, ...]]:
    """Label sumber karbohidrat yang benar-benar punya menu di dataset."""
    return _preference_options(CARB_PREFERENCE_CATEGORIES, foods, meal_slot)

IMAGE_CHECK_MAX_WORKERS = 20

LEVEL_ALLOWLIST = {
    "Beginner": {"Beginner"},
    "Intermediate": {"Beginner", "Intermediate"},
    "Expert": {"Beginner", "Intermediate", "Expert"},
}

# --------------------------------------------------------------------------- #
# Penyusunan program latihan
# --------------------------------------------------------------------------- #
# Komposisi jenis latihan per tujuan kebugaran, diambil berurutan; bila satu jenis
# kehabisan kandidat, sisanya jatuh ke jenis berikutnya. Dasarnya nilai MET pada
# EXERCISE_MET. Lihat docs/catatan-desain.md bagian 10.
EXERCISE_TYPE_PLAN = {
    "Lose Weight": [("Cardio", 1), ("Plyometrics", 1), ("Strength", 3)],
    "Maintain Weight": [("Plyometrics", 1), ("Strength", 4)],
    "Gain Weight": [("Strength", 4), ("Powerlifting", 1)],
}

# Urutan prioritas alat menurut level pengalaman, disusun menurut keamanan: mesin
# didahulukan untuk pemula karena jalur gerakannya terpandu, barbel bebas untuk
# expert. Dipakai _rank_exercise_candidates() sebagai kunci pengurut ketiga.
EQUIPMENT_PRIORITY = {
    "Beginner": ["Body Only", "Machine", "Dumbbell", "Bands", "Cable"],
    "Intermediate": ["Dumbbell", "Body Only", "Cable", "Machine", "Barbell", "Bands"],
    "Expert": ["Barbell", "Dumbbell", "Kettlebells", "Cable", "Body Only", "Machine",
               "E-Z Curl Bar", "Medicine Ball"],
}

# Tangga pelonggaran level. Lapis pertama adalah level pengguna sendiri; bila
# kolamnya kurang, naik satu lapis dan latihan tambahan itu ditandai pada kolom
# NEEDS_SUPERVISION_COLUMN. Lihat docs/catatan-desain.md bagian 11.
EXERCISE_LEVEL_LADDER = {
    "Beginner": [{"Beginner"}, {"Intermediate"}, {"Expert"}],
    "Intermediate": [{"Beginner", "Intermediate"}, {"Expert"}],
    "Expert": [{"Beginner", "Intermediate", "Expert"}],
}

# Nama kolom penanda pada hasil rekomendasi: True bila latihan itu diambil dari
# lapis level di atas level pengguna.
NEEDS_SUPERVISION_COLUMN = "Needs_Supervision"

# Jumlah latihan bawaan menurut level pengalaman dan tingkat aktivitas. Hanya nilai
# awal; pengguna tetap boleh menggesernya dalam rentang MIN..MAX_EXERCISE_COUNT.
# Alasan rentangnya: docs/catatan-desain.md bagian 12.
DEFAULT_EXERCISE_COUNT = {
    ("Beginner", "Low"): 3, ("Beginner", "Medium"): 3,
    ("Beginner", "High"): 4, ("Beginner", "Very High"): 4,
    ("Intermediate", "Low"): 4, ("Intermediate", "Medium"): 4,
    ("Intermediate", "High"): 5, ("Intermediate", "Very High"): 6,
    ("Expert", "Low"): 5, ("Expert", "Medium"): 5,
    ("Expert", "High"): 6, ("Expert", "Very High"): 6,
}

MIN_EXERCISE_COUNT, MAX_EXERCISE_COUNT = 3, 8


def default_exercise_count(experience_level: str, activity_level: str) -> int:
    """Jumlah latihan yang disarankan sistem, sebelum pengguna mengubahnya."""
    return DEFAULT_EXERCISE_COUNT.get(
        (str(experience_level), str(activity_level)),
        DEFAULT_EXERCISE_COUNT[("Intermediate", "Medium")],
    )

TARGET_MUSCLE_GROUPS = {
    "Dada": {"Chest"},
    "Bahu": {"Shoulders", "Traps"},
    "Punggung": {"Middle Back", "Lower Back"},
    "Lengan": {"Biceps", "Triceps", "Forearms"},
    "Core/Inti/Perut": {"Abdominals"},
    "Kaki": {"Quadriceps", "Hamstrings", "Glutes", "Calves", "Abductors", "Adductors"},
    "Sayap": {"Lats"},
}

TRAINING_PARAMETERS = {
    ("Lose Weight", "Beginner"): {"sets": 3, "reps": 15, "rest_seconds": 60},
    ("Lose Weight", "Intermediate"): {"sets": 4, "reps": 15, "rest_seconds": 60},
    ("Lose Weight", "Expert"): {"sets": 4, "reps": 20, "rest_seconds": 45},
    ("Gain Weight", "Beginner"): {"sets": 3, "reps": 10, "rest_seconds": 90},
    ("Gain Weight", "Intermediate"): {"sets": 4, "reps": 10, "rest_seconds": 90},
    ("Gain Weight", "Expert"): {"sets": 4, "reps": 12, "rest_seconds": 90},
    ("Maintain Weight", "Beginner"): {"sets": 3, "reps": 12, "rest_seconds": 75},
    ("Maintain Weight", "Intermediate"): {"sets": 3, "reps": 12, "rest_seconds": 75},
    ("Maintain Weight", "Expert"): {"sets": 4, "reps": 12, "rest_seconds": 75},
}


# --------------------------------------------------------------------------- #
# Estimasi kalori terbakar
# --------------------------------------------------------------------------- #
# Nilai MET (Metabolic Equivalent of Task) per jenis latihan, mengacu pada
# Compendium of Physical Activities. Dipakai estimate_exercise_calories():
#     kkal = MET x 3,5 x berat badan (kg) / 200 x durasi (menit)
EXERCISE_MET = {
    "Strength": 5.0,
    "Powerlifting": 6.0,
    "Olympic Weightlifting": 6.0,
    "Strongman": 6.0,
    "Plyometrics": 8.0,
    "Cardio": 7.0,
    "Stretching": 2.3,
}
DEFAULT_MET = 5.0

# Perkiraan waktu satu repetisi (detik). Repetisi terkontrol pada latihan beban
# umumnya 2-4 detik; 3 detik dipakai sebagai nilai tengah.
SECONDS_PER_REP = 3


def exercise_duration_minutes(exercise: dict) -> float:
    """Durasi satu latihan: seluruh set kerja ditambah istirahat antar-set.

    Istirahat setelah set TERAKHIR tidak dihitung -- pada set terakhir pengguna
    sudah berpindah ke gerakan berikutnya.
    """
    sets = _safe_int(exercise.get("sets"), default=3)
    reps = _safe_int(exercise.get("reps"), default=12)
    rest = _safe_int(exercise.get("rest_seconds"), default=60)
    work_seconds = sets * reps * SECONDS_PER_REP
    rest_seconds = max(sets - 1, 0) * rest
    return (work_seconds + rest_seconds) / 60


def estimate_exercise_calories(exercise: dict, weight_kg: float | None) -> float:
    """Perkiraan kalori terbakar untuk satu latihan, berbasis MET."""
    try:
        weight = float(weight_kg)
    except (TypeError, ValueError):
        weight = 0.0
    if weight <= 0:
        return 0.0
    met = EXERCISE_MET.get(str(exercise.get("Type", "")).strip(), DEFAULT_MET)
    return met * 3.5 * weight / 200 * exercise_duration_minutes(exercise)


def _safe_int(value, *, default: int) -> int:
    """Ubah nilai apa pun jadi bilangan bulat positif; pakai default bila gagal atau tidak positif."""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def normalize_goal(goal: str) -> str:
    """Samakan penulisan tujuan latihan dari dataset ke istilah yang dipakai aplikasi."""
    mapping = {
        "Weight Loss": "Lose Weight",
        "Lose Weight": "Lose Weight",
        "Weight Gain": "Gain Weight",
        "Gain Weight": "Gain Weight",
        "Weight Maintenance": "Maintain Weight",
        "Maintain Weight": "Maintain Weight",
    }
    return mapping.get(goal, goal)


def normalize_experience_level(level: str | int) -> str:
    """Samakan level pengalaman (angka 1-3 atau teks) jadi Beginner/Intermediate/Expert."""
    mapping = {
        1: "Beginner",
        2: "Intermediate",
        3: "Expert",
        "1": "Beginner",
        "2": "Intermediate",
        "3": "Expert",
        "Beginner": "Beginner",
        "Intermediate": "Intermediate",
        "Expert": "Expert",
    }
    return mapping.get(level, "Beginner")


def load_datasets() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Muat dan olah tiga dataset utama: anggota gym, menu makanan, dan program latihan."""
    members, foods, exercises = load_dataset_tables()
    return clean_members(members), prepare_foods(foods), prepare_exercises(exercises)


def load_dataset_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Baca tabel gym_members, food_nutrition, dan training_program mentah dari database."""
    store = SQLStore()
    with store.connection() as connection:
        with connection.cursor() as cursor:
            members = fetch_dataframe(
                cursor,
                """
                SELECT
                    age AS "Age",
                    gender AS "Gender",
                    weight_kg AS "Weight (kg)",
                    height_m AS "Height (m)",
                    max_bpm AS "Max_BPM",
                    avg_bpm AS "Avg_BPM",
                    resting_bpm AS "Resting_BPM",
                    session_duration_hours AS "Session_Duration (hours)",
                    calories_burned AS "Calories_Burned",
                    workout_type AS "Workout_Type",
                    fat_percentage AS "Fat_Percentage",
                    water_intake_liters AS "Water_Intake (liters)",
                    workout_frequency_days_week AS "Workout_Frequency (days/week)",
                    experience_level AS "Experience_Level",
                    bmi AS "BMI",
                    activity_level AS "Activity_Level",
                    fitness_goal AS "Fitness_Goal"
                FROM gym_members
                ORDER BY member_id
                """,
            )
            foods = fetch_dataframe(
                cursor,
                """
                SELECT id, calories, proteins, fat, carbohydrate, name, image
                FROM food_nutrition
                ORDER BY id
                """,
            )
            exercises = fetch_dataframe(
                cursor,
                """
                SELECT
                    program_id AS "Unnamed: 0",
                    title AS "Title",
                    description AS "Desc",
                    type AS "Type",
                    body_part AS "BodyPart",
                    equipment AS "Equipment",
                    level AS "Level",
                    rating AS "Rating",
                    rating_desc AS "RatingDesc"
                FROM training_program
                ORDER BY program_id
                """,
            )

    ensure_dataset_rows(members, foods, exercises)
    return members, foods, exercises


def fetch_dataframe(cursor, query: str) -> pd.DataFrame:
    """Jalankan satu query lalu bungkus hasilnya jadi DataFrame."""
    try:
        cursor.execute(query)
    except Exception as exc:
        raise RuntimeError("Dataset tables are not ready. Run python3 schema_data/import_csv_to_db.py first.") from exc
    return pd.DataFrame(cursor.fetchall())


def ensure_dataset_rows(members: pd.DataFrame, foods: pd.DataFrame, exercises: pd.DataFrame) -> None:
    """Hentikan proses dengan pesan jelas bila ada tabel dataset yang masih kosong."""
    empty_tables = []
    if members.empty:
        empty_tables.append("gym_members")
    if foods.empty:
        empty_tables.append("food_nutrition")
    if exercises.empty:
        empty_tables.append("training_program")
    if empty_tables:
        tables = ", ".join(empty_tables)
        raise RuntimeError(f"Dataset table(s) empty: {tables}. Run python3 schema_data/import_csv_to_db.py first.")


def clean_members(df: pd.DataFrame) -> pd.DataFrame:
    """Bersihkan data anggota gym, seragamkan label, lalu bubuhkan hasil klaster K-Prototypes.

    Kolom `User_Cluster` yang dihasilkan adalah keluaran SEGMENTASI dan ditampilkan
    sebagai label segmen; ia tidak dipakai menyusun rekomendasi menu maupun latihan.
    Alasannya: docs/catatan-desain.md bagian 9.
    """
    cleaned = df.copy()
    cleaned["Experience_Label"] = cleaned["Experience_Level"].apply(normalize_experience_level)
    cleaned["Fitness_Goal"] = cleaned["Fitness_Goal"].apply(normalize_goal)
    cleaned = cleaned.dropna(subset=["Age", "Gender", "Weight (kg)", "Height (m)", "BMI"])
    labels, model = fit_member_cluster_model(cleaned)
    cleaned["User_Cluster"] = pd.Series(labels + 1, index=cleaned.index)
    cleaned.attrs["member_cluster_model"] = model
    return cleaned


def assign_member_clusters(members: pd.DataFrame, n_clusters: int | None = None) -> pd.Series:
    """Label klaster K-Prototypes untuk tiap baris anggota, dimulai dari 1."""
    labels, _ = fit_member_cluster_model(members, n_clusters=n_clusters)
    return pd.Series(labels + 1, index=members.index)


def _evaluation_sample_index(size: int) -> np.ndarray | None:
    """Indeks sampel deterministik untuk matriks jarak, atau None kalau tidak perlu."""
    if size <= EVALUATION_SAMPLE_LIMIT:
        return None
    return np.linspace(0, size - 1, EVALUATION_SAMPLE_LIMIT, dtype=int)


# --------------------------------------------------------------------------- #
# Pencarian klaster -- Metode Siku (Elbow Method)
# --------------------------------------------------------------------------- #
# Untuk setiap kandidat K, sekumpulan titik awal diadu dan yang biayanya terendah
# yang dipakai; barisan biaya-terbaik-per-K itulah kurva yang dicari sikunya.
def elbow_distances(k_values, costs) -> np.ndarray:
    """Jarak tiap titik kurva biaya ke garis lurus yang menghubungkan kedua ujungnya.

    Kedua sumbu dinormalkan ke 0..1 lebih dulu supaya hasilnya tidak bergantung pada
    satuan biaya. Titik terjauh dari garis itulah tikungan paling tajam.
    """
    k = np.asarray(list(k_values), dtype=float)
    cost = np.asarray(list(costs), dtype=float)
    if len(k) < 3:
        return np.zeros(len(k))

    def normalkan(nilai: np.ndarray) -> np.ndarray:
        rentang = float(nilai.max() - nilai.min())
        return (nilai - nilai.min()) / rentang if rentang else np.zeros_like(nilai)

    x, y = normalkan(k), normalkan(cost)
    pangkal = np.array([x[0], y[0]])
    arah = np.array([x[-1], y[-1]]) - pangkal
    panjang = float(np.hypot(arah[0], arah[1]))
    if panjang == 0:
        return np.zeros(len(k))
    titik = np.column_stack([x, y]) - pangkal
    return np.abs(arah[0] * titik[:, 1] - arah[1] * titik[:, 0]) / panjang


def elbow_cluster_count(k_values, costs) -> int:
    """Jumlah klaster pada titik siku kurva biaya."""
    k_values = list(k_values)
    if len(k_values) == 1:
        return int(k_values[0])
    return int(k_values[int(np.argmax(elbow_distances(k_values, costs)))])


def elbow_table(k_values, costs, *, cost_label: str = "Cost") -> pd.DataFrame:
    """Tabel Metode Siku: biaya tiap K, penurunannya, dan jarak ke garis ujung-ke-ujung."""
    k_values = list(k_values)
    costs = [float(c) for c in costs]
    jarak = elbow_distances(k_values, costs)
    penurunan = [None] + [costs[i - 1] - costs[i] for i in range(1, len(costs))]
    siku = elbow_cluster_count(k_values, costs)
    return pd.DataFrame(
        {
            "K": k_values,
            cost_label: np.round(costs, 4),
            "Penurunan": [None if p is None else round(p, 4) for p in penurunan],
            "Jarak ke garis": np.round(jarak, 4),
            "Titik siku": ["<-- K dipilih" if k == siku else "" for k in k_values],
        }
    )


def member_cost_curve(
    numeric: np.ndarray,
    categorical: np.ndarray,
    k_values: Iterable[int] | None = None,
) -> list[tuple[int, float, np.ndarray, np.ndarray, np.ndarray]]:
    """Biaya terbaik per K untuk K-Prototypes, lengkap dengan klaster pemenangnya.

    Dipakai bersama oleh aplikasi (lewat `search_member_clusters`) dan notebook
    pengujian, supaya kurva siku yang digambar notebook adalah kurva yang sama
    yang menentukan K di aplikasi.
    """
    kandidat = list(k_values) if k_values is not None else list(CLUSTER_SEARCH_RANGE)
    kurva = []
    for k in kandidat:
        if k >= len(numeric):
            continue
        terbaik = None
        for seed in [None, *range(MEMBER_INIT_ATTEMPTS)]:
            labels, numeric_modes, categorical_modes = fit_kprototypes(
                numeric, categorical, n_clusters=k, random_state=seed
            )
            cost = kprototypes_total_cost(numeric, categorical, labels, numeric_modes, categorical_modes)
            if terbaik is None or cost < terbaik[0]:
                terbaik = (cost, labels, numeric_modes, categorical_modes)
        if terbaik is not None:
            kurva.append((k, *terbaik))
    return kurva


def exercise_cost_curve(
    categorical: pd.DataFrame,
    k_values: Iterable[int] | None = None,
) -> list[tuple[int, float, np.ndarray, np.ndarray]]:
    """Biaya terbaik per K untuk K-Modes, lengkap dengan klaster pemenangnya.

    Biayanya BERBOBOT -- sama dengan yang benar-benar diminimalkan `fit_kmodes`.
    Hamming Cost polos yang dilaporkan di tabel hasil dihitung terpisah, sebagai
    keterangan, bukan sebagai dasar pemilihan K.
    """
    values = categorical.astype(str).to_numpy()
    weights = categorical_attribute_weights(values)
    kandidat = list(k_values) if k_values is not None else list(CLUSTER_SEARCH_RANGE)
    kurva = []
    for k in kandidat:
        if k >= len(values):
            continue
        terbaik = None
        for seed in [None, *range(EXERCISE_INIT_ATTEMPTS)]:
            labels, modes = fit_kmodes(categorical, n_clusters=k, random_state=seed)
            if len(np.unique(labels)) < 2:
                continue
            cost = kmodes_total_cost(values, labels, modes, weights=weights)
            if terbaik is None or cost < terbaik[0]:
                terbaik = (cost, labels, modes)
        if terbaik is not None:
            kurva.append((k, *terbaik))
    return kurva


def search_member_clusters(
    numeric: np.ndarray,
    categorical: np.ndarray,
    *,
    n_clusters: int | None = None,
) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
    """Tetapkan K dengan Metode Siku atas Total Cost, lalu balas klaster untuk K itu."""
    kurva = member_cost_curve(numeric, categorical, [n_clusters] if n_clusters else None)

    if not kurva:  # dataset terlalu kecil untuk dibagi -- kembalikan satu klaster
        k = max(1, min(n_clusters or CLUSTER_SEARCH_RANGE.start, len(numeric)))
        labels, numeric_modes, categorical_modes = fit_kprototypes(numeric, categorical, n_clusters=k)
        return k, labels, numeric_modes, categorical_modes

    terpilih = elbow_cluster_count([baris[0] for baris in kurva], [baris[1] for baris in kurva])
    k, _, labels, numeric_modes, categorical_modes = next(b for b in kurva if b[0] == terpilih)
    return k, labels, numeric_modes, categorical_modes


def search_exercise_clusters(categorical: pd.DataFrame) -> tuple[int, np.ndarray, np.ndarray]:
    """Tetapkan K dengan Metode Siku atas Hamming Cost berbobot, lalu balas klaster untuk K itu."""
    kurva = exercise_cost_curve(categorical)

    if not kurva:
        k = max(1, min(CLUSTER_SEARCH_RANGE.start, len(categorical)))
        labels, modes = fit_kmodes(categorical, n_clusters=k)
        return k, labels, modes

    terpilih = elbow_cluster_count([baris[0] for baris in kurva], [baris[1] for baris in kurva])
    k, _, labels, modes = next(b for b in kurva if b[0] == terpilih)
    return k, labels, modes


def optimal_member_clusters(numeric: np.ndarray, categorical: np.ndarray) -> int:
    """Jumlah klaster anggota yang dipakai aplikasi."""
    return search_member_clusters(numeric, categorical)[0]


def optimal_exercise_clusters(categorical: pd.DataFrame) -> int:
    """Jumlah klaster latihan yang dipakai aplikasi."""
    return search_exercise_clusters(categorical)[0]


def fit_member_cluster_model(members: pd.DataFrame, n_clusters: int | None = None) -> tuple[np.ndarray, dict]:
    """Latih K-Prototypes pada data anggota; balas label plus modus dan scaler untuk memetakan user baru."""
    numeric_columns = MEMBER_NUMERIC_COLUMNS
    categorical_columns = MEMBER_CATEGORICAL_COLUMNS
    numeric, categorical, scaler = member_feature_matrices(members, numeric_columns, categorical_columns)
    # Pencarian mengembalikan sekalian label dan modus pemenangnya, jadi tidak
    # perlu melatih ulang setelah K ketemu.
    _, labels, numeric_modes, categorical_modes = search_member_clusters(
        numeric, categorical, n_clusters=n_clusters
    )
    model = {
        "numeric_columns": numeric_columns,
        "categorical_columns": categorical_columns,
        "scaler": scaler,
        "numeric_modes": numeric_modes,
        "categorical_modes": categorical_modes,
    }
    return labels, model


def prepare_foods(df: pd.DataFrame) -> pd.DataFrame:
    """Bersihkan dan saring data menu, bubuhkan klaster K-Means, kategori, dan teks TF-IDF."""
    foods = df.copy()
    foods = foods.dropna(subset=["name", "calories", "proteins", "fat", "carbohydrate"])
    for column in ["calories", "proteins", "fat", "carbohydrate"]:
        foods[column] = pd.to_numeric(foods[column], errors="coerce").fillna(0)
    foods = foods[foods["calories"] > 0].reset_index(drop=True)
    foods = filter_recommendable_foods(foods).reset_index(drop=True)
    foods["Food_Cluster"] = assign_food_clusters(foods)
    foods["Is_Snack"] = snack_eligibility(foods)
    foods["Food_Category"] = primary_food_category(foods)
    # Teks CBF berisi NAMA MENU SAJA. Nilai gizi, label klaster, dan kategori
    # sengaja tidak ikut: angka menjadi token yang mustahil dicocokkan, token yang
    # dimiliki semua baris ber-IDF nol, dan kategori adalah kebocoran label karena
    # ia juga dipakai menilai relevansi. Lihat docs/catatan-desain.md bagian 4.
    foods["CBF_Text"] = foods["name"].fillna("").astype(str)
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(foods["CBF_Text"])
    foods.attrs["food_tfidf_model"] = {"vectorizer": vectorizer, "tfidf_matrix": tfidf_matrix}
    return foods


def _lowercase_names(foods: pd.DataFrame) -> pd.Series:
    """Nama menu dalam huruf kecil tanpa spasi berlebih, untuk pencocokan pola."""
    return foods["name"].fillna("").astype(str).str.lower().str.strip()


def snack_eligibility(foods: pd.DataFrame) -> pd.Series:
    """True untuk item yang pantas disajikan di slot camilan.

    Dinilai dari BENTUK SAJIAN, bukan jumlah kalorinya: sepiring nasi tetap makanan
    berat walaupun porsinya dipotong jadi 80 gram.
    """
    names = _lowercase_names(foods)
    always = names.str.contains(SNACK_ALWAYS_PATTERN, regex=True, na=False)
    snack_form = names.str.contains(SNACK_FORM_PATTERN, regex=True, na=False)
    main_dish = names.str.contains(NOT_SNACK_PATTERN, regex=True, na=False)
    return always | (snack_form & ~main_dish)


def food_category_mask(foods: pd.DataFrame, label: str) -> pd.Series:
    """Baris yang termasuk satu kategori bahan utama."""
    names = _lowercase_names(foods)
    if label == OTHER_CATEGORY:
        mask = pd.Series(True, index=foods.index)
        for other in FOOD_CATEGORIES:
            mask &= ~food_category_mask(foods, other)
        return mask

    patterns = FOOD_CATEGORIES.get(label)
    if not patterns:
        return pd.Series(False, index=foods.index)
    include, exclude = patterns
    mask = names.str.contains(include, regex=True, na=False)
    if exclude:
        mask &= ~names.str.contains(exclude, regex=True, na=False)
    return mask


def match_food_categories(foods: pd.DataFrame, labels: Iterable[str] | None) -> pd.Series:
    """Gabungan (OR) dari beberapa kategori. Tanpa pilihan = semua lolos."""
    selected = [label for label in (labels or []) if label]
    if not selected:
        return pd.Series(True, index=foods.index)
    mask = pd.Series(False, index=foods.index)
    for label in selected:
        mask |= food_category_mask(foods, label)
    return mask


def primary_food_category(foods: pd.DataFrame) -> pd.Series:
    """Satu label kategori per item, dipakai untuk chip di kartu menu.

    Kategori pertama yang cocok yang menang, jadi urutan FOOD_CATEGORIES
    sekaligus menyatakan prioritas: bahan hewani lebih dulu, baru olahan pati.
    """
    result = pd.Series(OTHER_CATEGORY, index=foods.index, dtype=object)
    assigned = pd.Series(False, index=foods.index)
    for label in FOOD_CATEGORIES:
        mask = food_category_mask(foods, label) & ~assigned
        result[mask] = label
        assigned |= mask
    return result


@lru_cache(maxsize=2048)
def food_categories_for_name(name: str) -> tuple[str, ...]:
    """SELURUH kategori yang dimiliki satu menu, bukan hanya yang menang prioritas.

    Memakai `food_category_mask()`, definisi yang sama yang dipakai `_rank_foods()`
    untuk menyaring, sehingga chip yang tampil di kartu menu sejalan dengan kategori
    yang benar-benar dipakai sistem. Hasilnya di-cache karena dipanggil per kartu.
    """
    frame = pd.DataFrame({"name": [name or ""]})
    labels = tuple(
        label for label in FOOD_CATEGORIES if bool(food_category_mask(frame, label).iloc[0])
    )
    return labels or (OTHER_CATEGORY,)


def available_food_categories(foods: pd.DataFrame, *, meal_slot: str | None = None) -> list[str]:
    """Kategori yang benar-benar punya isi di dataset (opsional: untuk satu slot).

    Slot camilan hanya menampilkan kategori yang punya item layak camilan --
    itulah sebabnya "Nasi & Olahan Beras" dan "Mie & Bihun" tidak pernah
    ditawarkan sebagai pilihan camilan.
    """
    pool = foods
    if meal_slot == SNACK_SLOT and "Is_Snack" in foods.columns:
        pool = foods[foods["Is_Snack"]]
    if pool.empty:
        return []
    return [
        label
        for label in (*FOOD_CATEGORIES, OTHER_CATEGORY)
        if bool(food_category_mask(pool, label).any())
    ]


def slot_calorie_quota(target_calories: float) -> dict[str, int]:
    """Kuota kalori tiap slot = kebutuhan energi harian x proporsi slot.

    Dibulatkan dengan metode sisa terbesar sehingga penjumlahan keempat slot persis
    sama dengan target kalori harian.
    """
    total = int(round(float(target_calories)))
    exact = {slot: total * ratio for slot, ratio in MEAL_DISTRIBUTION.items()}
    quota = {slot: int(value) for slot, value in exact.items()}
    leftover = total - sum(quota.values())
    by_remainder = sorted(exact, key=lambda slot: exact[slot] - quota[slot], reverse=True)
    for slot in by_remainder[:leftover]:
        quota[slot] += 1
    return quota


def portion_gram_for_calories(target_calories: float, calories_per_100g: float) -> float | None:
    """Persamaan Konversi Kalori ke Gramasi.

        gramasi (g) = (kuota kalori (kkal) / kalori per 100 g) x 100
    """
    if not calories_per_100g or calories_per_100g <= 0:
        return None
    return (float(target_calories) / float(calories_per_100g)) * 100


def portion_is_realistic(portion_gram: float | None) -> bool:
    """Volumetric Sanity Check."""
    if portion_gram is None:
        return False
    return MIN_PORTION_GRAM <= portion_gram <= MAX_PORTION_GRAM


def nutrition_is_plausible(foods: pd.DataFrame) -> pd.Series:
    """True untuk baris yang nilai gizinya mungkin secara fisik.

    Dua pemeriksaan: massa protein + lemak + karbohidrat tidak melebihi 100 g per
    100 g bahan, dan energi tercatat mendekati hasil hitung faktor Atwater (4-9-4).
    Baris yang gagal dibuang, bukan diperbaiki.
    """
    protein = pd.to_numeric(foods["proteins"], errors="coerce").fillna(0)
    fat = pd.to_numeric(foods["fat"], errors="coerce").fillna(0)
    carbohydrate = pd.to_numeric(foods["carbohydrate"], errors="coerce").fillna(0)
    calories = pd.to_numeric(foods["calories"], errors="coerce").fillna(0)

    mass_is_possible = (protein + fat + carbohydrate) <= NUTRITION_MASS_LIMIT_GRAM
    atwater = protein * 4 + fat * 9 + carbohydrate * 4
    deviation = (calories - atwater).abs() / calories.where(calories > 0, other=np.nan)
    energy_agrees = deviation.fillna(1.0) <= NUTRITION_ENERGY_TOLERANCE
    return mass_is_possible & energy_agrees


def filter_recommendable_foods(foods: pd.DataFrame) -> pd.DataFrame:
    """Buang entri yang bukan hidangan siap santap, lalu bubuhkan status gambar.

    Delapan aturan penolakan beserta jumlah baris yang terkena:
    docs/catatan-desain.md bagian 14.
    """
    names = foods["name"].fillna("").astype(str).str.lower().str.strip()
    is_not_human_food = names.str.contains(NOT_HUMAN_FOOD_PATTERN, regex=True, na=False)
    is_ingredient = names.str.contains(INGREDIENT_PATTERN, regex=True, na=False)
    is_fruit_ingredient = names.str.contains(FRUIT_AS_INGREDIENT_PATTERN, regex=True, na=False)
    is_excluded = names.str.contains(EXCLUDED_FOOD_PATTERN, regex=True, na=False)
    is_protected = names.str.contains(PROTECTED_OR_HARAM_DISH_PATTERN, regex=True, na=False)
    is_salt_cured = names.str.contains(SALT_CURED_PROTEIN_PATTERN, regex=True, na=False)
    # "segar" menandai bahan mentah KECUALI pada buah, yang justru siap santap
    # dalam bentuk itu. Pengecualiannya hanya menetralkan aturan "segar";
    # aturan lain tetap berlaku penuh, jadi "Jantung Pisang segar" tetap gugur.
    is_raw_fresh = names.str.contains(RAW_FRESH_PATTERN, regex=True, na=False) & ~names.str.contains(
        FRESH_FRUIT_PATTERN, regex=True, na=False
    )
    is_not_a_meal = names.str.contains(NOT_A_MEAL_PATTERN, regex=True, na=False)
    passes_name_filter = (
        ~is_not_human_food
        & ~is_ingredient
        & ~is_raw_fresh
        & ~is_fruit_ingredient
        & ~is_excluded
        & ~is_protected
        & ~is_salt_cured
        & ~is_not_a_meal
        & nutrition_is_plausible(foods)
    )

    # Ketersediaan gambar tidak menentukan apakah sebuah menu boleh direkomendasikan.
    # Statusnya dibaca dari cache saja, tanpa permintaan jaringan saat start; menu
    # tanpa gambar tetap muncul dengan gambar pengganti.
    candidates = foods[passes_name_filter].copy()
    images = candidates["image"].fillna("").astype(str)
    candidates["Has_Image"] = pd.Series(
        image_status_from_cache(images.tolist()), index=images.index, dtype=bool
    )
    return candidates


def image_status_from_cache(urls: list[str]) -> list[bool]:
    """Status gambar dari cache di disk. TIDAK menyentuh jaringan.

    URL yang belum pernah diperiksa dianggap bisa ditampilkan (optimistis).
    """
    if not urls:
        return []
    cached = _load_image_cache()
    return [
        bool(url) and url.startswith(("http://", "https://")) and cached.get(url, True)
        for url in urls
    ]


def check_image_urls_concurrently(urls: list[str], max_workers: int = IMAGE_CHECK_MAX_WORKERS) -> list[bool]:
    """Periksa banyak URL gambar sekaligus memakai thread pool.

    Hasilnya disimpan ke cache disk supaya restart berikutnya tidak menembak ulang
    seluruh URL. URL yang kena pembatasan laju tidak ikut disimpan.
    """
    if not urls:
        return []

    # Hasil pemeriksaan disimpan ke disk supaya restart berikutnya tidak menembak
    # ratusan URL lagi. Cache ini murni optimasi: hasilnya tetap benar tanpanya.
    cached = _load_image_cache()
    pending = [url for url in dict.fromkeys(urls) if url not in cached]
    if pending:
        workers = max(1, min(max_workers, len(pending)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            cached.update(zip(pending, executor.map(image_url_is_displayable, pending)))
        # URL yang kena pembatasan laju tidak ikut disimpan supaya diperiksa ulang.
        layak_disimpan = {url: ok for url, ok in cached.items() if url not in _THROTTLED_URLS}
        _save_image_cache(layak_disimpan)
    return [cached[url] for url in urls]


IMAGE_CACHE_PATH = DATA_DIR / ".image_check_cache.json"

# Masa berlaku cache status gambar. Salah tebak paling banter menampilkan gambar
# pengganti pada menu yang sebetulnya punya gambar.
IMAGE_CACHE_TTL_SECONDS = 90 * 24 * 60 * 60


def _load_image_cache() -> dict[str, bool]:
    """Baca cache hasil cek gambar, buang entri yang sudah kedaluwarsa."""
    try:
        raw = json.loads(IMAGE_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    now = time.time()
    fresh = {}
    for url, entry in raw.items():
        # entri = [hasil_bool, waktu_simpan]
        if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], bool):
            try:
                if now - float(entry[1]) < IMAGE_CACHE_TTL_SECONDS:
                    fresh[url] = entry[0]
            except (TypeError, ValueError):
                continue
    return fresh


def _save_image_cache(results: dict[str, bool]) -> None:
    """Tulis hasil pemeriksaan URL gambar ke cache disk; kegagalan menulis diabaikan."""
    now = time.time()
    payload = {url: [bool(ok), now] for url, ok in results.items()}
    try:
        IMAGE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        IMAGE_CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass  # gagal nulis cache tidak boleh menjatuhkan app


# Kode HTTP yang berarti "server hidup tapi sedang menolak permintaan ini",
# BUKAN "gambarnya tidak ada". Dibedakan karena keduanya dulu sama-sama
# dianggap gambar mati -- lihat penjelasan di image_url_is_displayable.
THROTTLED_STATUS = {429, 500, 502, 503, 504}

# URL yang jawabannya tidak bisa dipastikan pada proses ini. Hasilnya sengaja
# TIDAK ikut disimpan ke cache disk supaya diperiksa lagi lain kali.
_THROTTLED_URLS: set[str] = set()


@lru_cache(maxsize=2048)
def image_url_is_displayable(url: str) -> bool:
    """Cek lewat HEAD apakah URL benar-benar mengembalikan gambar; hasilnya di-cache per proses."""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False

    request = Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=3) as response:
            return image_response_is_valid(response)
    except HTTPError as exc:
        if exc.code in {403, 405}:
            return image_url_is_displayable_with_get(url)
        if exc.code in THROTTLED_STATUS:
            # Pembatasan laju bukan tanda gambarnya mati; dijawab optimistis dan
            # ditandai supaya hasilnya tidak ikut disimpan ke cache.
            _THROTTLED_URLS.add(url)
            return True
        return False
    except (OSError, HTTPException, ValueError):
        # Galat jaringan lain diperlakukan sebagai gambar tidak bisa ditampilkan.
        return False


def image_url_is_displayable_with_get(url: str) -> bool:
    """Cek ulang dengan GET terbatas untuk host yang menolak permintaan HEAD."""
    request = Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-2048"})
    try:
        with urlopen(request, timeout=3) as response:
            return image_response_is_valid(response)
    except (HTTPError, OSError, HTTPException, ValueError):
        return False


def image_response_is_valid(response) -> bool:
    """True bila status respons sukses dan Content-Type-nya bertipe image."""
    status = getattr(response, "status", 200)
    content_type = response.headers.get("Content-Type", "").lower()
    return 200 <= status < 400 and content_type.startswith("image/")


def food_cluster_features(foods: pd.DataFrame) -> np.ndarray:
    """Matriks fitur K-Means makanan: empat makro + kepadatan protein, diskalakan MinMax.

    Dipakai bersama oleh pembentuk klaster dan penilai performa, supaya angka yang
    dilaporkan berasal dari ruang fitur yang sama persis dengan yang membentuk
    klasternya.
    """
    work = foods[FOOD_MACRO_COLUMNS].copy()
    # Kalori nol sudah disaring prepare_foods(), tapi penjagaan ini membuat fungsi
    # tetap aman dipanggil dari notebook pengujian atas DataFrame mentah.
    kalori = work["calories"].replace(0, np.nan)
    work[FOOD_PROTEIN_DENSITY_COLUMN] = (work["proteins"] / kalori * 100).fillna(0)
    return MinMaxScaler().fit_transform(work)


def assign_food_clusters(foods: pd.DataFrame) -> pd.Series:
    """Klasterkan menu dengan K-Means lalu beri satu peran gizi pada tiap klaster.

    Perannya: A tinggi karbohidrat, B protein ramping, C rendah kalori,
    D protein berlemak. Pemetaannya total dan gagal keras bila jumlah peran tidak
    sama dengan jumlah klaster.
    """
    scaled = food_cluster_features(foods)
    labels = KMeans(n_clusters=FOOD_CLUSTER_COUNT, random_state=42, n_init=10).fit_predict(scaled)

    ringkas = foods.assign(_cluster=labels).groupby("_cluster")[FOOD_MACRO_COLUMNS].mean()
    ringkas[FOOD_PROTEIN_DENSITY_COLUMN] = ringkas["proteins"] / ringkas["calories"] * 100
    if len(ringkas) != FOOD_CLUSTER_COUNT:
        raise RuntimeError(
            f"K-Means menghasilkan {len(ringkas)} klaster, bukan {FOOD_CLUSTER_COUNT}; "
            "peran gizi tidak bisa dipetakan tanpa menebak."
        )

    # Urutan penetapan dari yang paling tidak ambigu ke yang paling halus. Dua
    # klaster terakhir dibedakan oleh KEPADATAN protein, bukan protein mutlak.
    rendah_kalori = ringkas["calories"].idxmin()
    sisa = [k for k in ringkas.index if k != rendah_kalori]
    karbohidrat = ringkas.loc[sisa, "carbohydrate"].idxmax()
    sisa = [k for k in sisa if k != karbohidrat]
    protein_ramping = ringkas.loc[sisa, FOOD_PROTEIN_DENSITY_COLUMN].idxmax()
    protein_berlemak = next(k for k in sisa if k != protein_ramping)

    peran = {
        karbohidrat: "A",
        protein_ramping: "B",
        rendah_kalori: "C",
        protein_berlemak: "D",
    }
    if len(peran) != FOOD_CLUSTER_COUNT:
        raise RuntimeError("Satu klaster mendapat lebih dari satu peran gizi; pemetaan tidak sah.")
    return pd.Series(labels).map(peran)


def prepare_exercises(df: pd.DataFrame) -> pd.DataFrame:
    """Bersihkan data latihan, bubuhkan klaster K-Modes, dan susun teks untuk TF-IDF."""
    exercises = df.copy()
    if "Unnamed: 0" in exercises.columns:
        exercises = exercises.rename(columns={"Unnamed: 0": "Program_ID"})
    required = ["Title", "Desc", "Type", "BodyPart", "Equipment", "Level"]
    exercises = exercises.dropna(subset=required).reset_index(drop=True)
    for column in required:
        exercises[column] = exercises[column].astype(str)
    exercises["Exercise_Cluster"] = assign_exercise_clusters(exercises)
    # Teks CBF latihan berisi JUDUL + DESKRIPSI SAJA. Type, BodyPart, Equipment, dan
    # Level sudah bekerja sebagai penyaring sehingga ber-IDF nol di dalam kolam, dan
    # nilainya pecah jadi token yang bertabrakan dengan prosa deskripsi.
    # Lihat docs/catatan-desain.md bagian 5.
    exercises["CBF_Text"] = exercises["Title"] + " " + exercises["Desc"]
    return exercises


def exercise_cluster_features(exercises: pd.DataFrame) -> pd.DataFrame:
    """Empat atribut kategorikal yang jadi masukan K-Modes latihan."""
    return exercises[["Type", "BodyPart", "Equipment", "Level"]].fillna("Unknown")


def assign_exercise_clusters(exercises: pd.DataFrame) -> pd.Series:
    """Label klaster K-Modes untuk tiap baris latihan."""
    _, labels, _ = search_exercise_clusters(exercise_cluster_features(exercises))
    return pd.Series(labels, index=exercises.index)


def assign_user_cluster(members: pd.DataFrame, profile: dict) -> int:
    """Tentukan klaster anggota yang paling dekat dengan profil pengguna baru."""
    model = members.attrs.get("member_cluster_model")
    if not model:
        raise RuntimeError("Member cluster model is not available. Load members through clean_members() first.")

    numeric_columns = model["numeric_columns"]
    categorical_columns = model["categorical_columns"]
    scaler = model["scaler"]
    numeric_modes = model["numeric_modes"]
    categorical_modes = model["categorical_modes"]

    profile_numeric = pd.DataFrame(
        [[profile["age"], profile["weight_kg"], profile["height_cm"] / 100, profile["bmi"]]],
        columns=numeric_columns,
    )
    profile_numeric_scaled = scaler.transform(profile_numeric)[0]
    profile_categories = np.array(
        [
            str(profile["gender"]),
            str(profile["activity_level"]),
            str(profile["experience_level"]),
            str(normalize_goal(profile["fitness_goal"])),
        ]
    )

    # Jarak dihitung dengan fungsi yang SAMA yang membentuk klasternya, supaya
    # pengguna baru tidak bisa mendarat di klaster yang bukan klaster terdekat.
    distances = kprototypes_distances(
        profile_numeric_scaled.reshape(1, -1),
        profile_categories.reshape(1, -1),
        numeric_modes,
        categorical_modes,
    )
    return int(distances[0].argmin()) + 1


def member_feature_matrices(
    members: pd.DataFrame,
    numeric_columns: list[str],
    categorical_columns: list[str],
) -> tuple[np.ndarray, np.ndarray, MinMaxScaler]:
    """Susun matriks numerik terskala dan matriks kategorikal dari data anggota."""
    work = members.copy()
    work["Height (m)"] = work["Height (m)"].where(work["Height (m)"] < 3, work["Height (m)"] / 100)
    scaler = MinMaxScaler()
    numeric = scaler.fit_transform(work[numeric_columns])
    categorical = work[categorical_columns].fillna("Unknown").astype(str).to_numpy()
    return numeric, categorical, scaler


def _initial_centroid_indices(size: int, n_clusters: int, random_state: int | None) -> np.ndarray:
    """Baris mana yang dipakai sebagai titik awal klaster.

    Tanpa `random_state`, titik awalnya deterministik (disebar merata lewat
    np.linspace) -- itu yang dipakai aplikasi. Dengan `random_state`, titik awalnya
    diundi; dipakai notebook pengujian untuk mengukur kepekaan terhadap inisialisasi.
    """
    if random_state is None:
        return np.linspace(0, size - 1, n_clusters, dtype=int)
    return np.random.default_rng(random_state).choice(size, size=n_clusters, replace=False)


def fit_kprototypes(
    numeric: np.ndarray,
    categorical: np.ndarray,
    n_clusters: int,
    *,
    max_iter: int = 30,
    random_state: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Satu kali K-Prototypes dari SATU titik awal.

    Pemilihan titik awal terbaik dilakukan di fit_member_cluster_model(), bukan di sini.
    """
    n_clusters = max(1, min(n_clusters, len(numeric)))
    init_indices = _initial_centroid_indices(len(numeric), n_clusters, random_state)
    numeric_modes = numeric[init_indices].copy()
    categorical_modes = categorical[init_indices].copy()
    labels = np.zeros(len(numeric), dtype=int)

    for _ in range(max_iter):
        distances = kprototypes_distances(numeric, categorical, numeric_modes, categorical_modes)
        new_labels = distances.argmin(axis=1)
        if np.array_equal(labels, new_labels):
            break
        labels = new_labels

        for cluster in range(n_clusters):
            mask = labels == cluster
            if not mask.any():
                continue
            numeric_modes[cluster] = numeric[mask].mean(axis=0)
            categorical_modes[cluster] = categorical_mode_rows(categorical[mask])

    return labels, numeric_modes, categorical_modes


def kprototypes_total_cost(
    numeric: np.ndarray,
    categorical: np.ndarray,
    labels: np.ndarray,
    numeric_modes: np.ndarray,
    categorical_modes: np.ndarray,
) -> float:
    """Total jarak setiap anggota ke modus klasternya sendiri."""
    distances = kprototypes_distances(numeric, categorical, numeric_modes, categorical_modes)
    return float(distances[np.arange(len(labels)), labels].sum())


def member_categorical_weights() -> np.ndarray:
    """Bobot tiap atribut kategorikal anggota, urut sesuai MEMBER_CATEGORICAL_COLUMNS.

    Dibangun dari nama kolom, bukan ditulis sebagai daftar angka, supaya bobotnya
    tetap menempel pada atribut yang benar walaupun urutan kolomnya berubah.
    """
    return np.array(
        [MEMBER_CATEGORICAL_WEIGHTS.get(column, 1.0) for column in MEMBER_CATEGORICAL_COLUMNS],
        dtype=float,
    )


def kprototypes_distances(
    numeric: np.ndarray,
    categorical: np.ndarray,
    numeric_modes: np.ndarray,
    categorical_modes: np.ndarray,
    weights: np.ndarray | None = None,
) -> np.ndarray:
    """Matriks jarak K-Prototypes tiap baris ke tiap modus.

    Jaraknya kuadrat Euclid pada atribut numerik ditambah ketidakcocokan kategorikal
    berbobot. `weights` bawaannya bobot anggota, bukan vektor satuan, supaya keempat
    pemakainya -- pembentuk klaster, Metode Siku, penilai performa, dan pemetaan
    pengguna baru -- memakai bobot yang sama persis.
    """
    if weights is None:
        weights = member_categorical_weights()
    numeric_distance = ((numeric[:, None, :] - numeric_modes[None, :, :]) ** 2).sum(axis=2)
    categorical_distance = (
        (categorical[:, None, :] != categorical_modes[None, :, :]) * weights
    ).sum(axis=2)
    return numeric_distance + categorical_distance


def categorical_attribute_weights(values: np.ndarray) -> np.ndarray:
    """Bobot penyeimbang antar-atribut untuk jarak Hamming.

    Tiap atribut diberi bobot berbanding terbalik dengan peluangnya berbeda pada dua
    baris acak, lalu dinormalkan agar rata-ratanya satu, sehingga atribut yang
    sebarannya nyaris seragam tetap ikut membedakan data.
    Nilai bobot pada dataset ini: docs/catatan-desain.md bagian 3.
    """
    rows = len(values)
    probabilities = []
    for column in range(values.shape[1]):
        counts = np.unique(values[:, column], return_counts=True)[1]
        share = counts / rows
        probabilities.append(1.0 - float((share ** 2).sum()))
    probability = np.array(probabilities)
    # Atribut yang benar-benar konstan tidak boleh membuat pembagian nol; ia
    # memang tidak membawa informasi, jadi bobotnya dibiarkan netral.
    probability[probability <= 0] = 1.0
    weights = 1.0 / probability
    return weights / weights.mean()


def fit_kmodes(
    categorical: pd.DataFrame,
    *,
    n_clusters: int,
    max_iter: int = 30,
    random_state: int | None = None,
    weights: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Satu kali K-Modes dari SATU titik awal.

    `weights` bawaannya bobot penyeimbang dari data itu sendiri; berikan array satuan
    untuk mendapatkan Hamming polos.
    """
    values = categorical.astype(str).to_numpy()
    n_clusters = max(1, min(n_clusters, len(values)))
    if weights is None:
        weights = categorical_attribute_weights(values)
    init_indices = _initial_centroid_indices(len(values), n_clusters, random_state)
    modes = values[init_indices].copy()
    labels = np.zeros(len(values), dtype=int)

    for _ in range(max_iter):
        distances = (values[:, None, :] != modes[None, :, :]).astype(float) @ weights
        new_labels = distances.argmin(axis=1)
        if np.array_equal(labels, new_labels):
            break
        labels = new_labels

        for cluster in range(n_clusters):
            mask = labels == cluster
            if mask.any():
                modes[cluster] = categorical_mode_rows(values[mask])

    return labels, modes


def kmodes_total_cost(
    values: np.ndarray,
    labels: np.ndarray,
    modes: np.ndarray,
    *,
    weights: np.ndarray | None = None,
) -> float:
    """Total ketidakcocokan setiap baris terhadap modus klasternya sendiri.

    Inilah fungsi biaya K-Modes yang diminimalkan saat melatih dan yang kurvanya
    dicari sikunya. Tanpa `weights` hasilnya Hamming Cost polos.
    """
    mismatch = (values[:, None, :] != modes[None, :, :]).astype(float)
    if weights is not None:
        distances = mismatch @ weights
    else:
        distances = mismatch.sum(axis=2)
    return float(distances[np.arange(len(labels)), labels].sum())


def hamming_separation_ratio(distances: np.ndarray, labels: np.ndarray) -> float:
    """Rata-rata jarak Hamming DALAM klaster dibagi rata-rata jarak ANTAR klaster.

    Makin kecil makin baik. `distances` adalah matriks jarak yang sudah dihitung
    sebelumnya dan tidak bergantung pada label, jadi cukup dihitung sekali.
    """
    same_cluster = labels[:, None] == labels[None, :]
    off_diagonal = ~np.eye(len(labels), dtype=bool)
    within_mask = same_cluster & off_diagonal
    between_mask = (~same_cluster) & off_diagonal
    if not within_mask.any() or not between_mask.any():
        return 1.0
    return float(distances[within_mask].mean() / distances[between_mask].mean())


def categorical_mode_rows(values: np.ndarray) -> np.ndarray:
    """Modus (nilai tersering) tiap kolom kategorikal dalam satu klaster."""
    modes = []
    for column_index in range(values.shape[1]):
        values_in_column, counts = np.unique(values[:, column_index], return_counts=True)
        modes.append(values_in_column[counts.argmax()])
    return np.array(modes)


def clustering_performance_report(
    members: pd.DataFrame,
    foods: pd.DataFrame,
    exercises: pd.DataFrame,
) -> dict[str, dict]:
    """Rangkum performa ketiga algoritma klasterisasi untuk halaman pengujian."""
    return {
        "K-Prototypes Profil Anggota": kprototypes_performance(members),
        "K-Means Menu Makanan": kmeans_food_performance(foods),
        "K-Modes Latihan": kmodes_exercise_performance(exercises),
    }


def kprototypes_performance(members: pd.DataFrame) -> dict:
    """Ukur performa K-Prototypes: cost, Silhouette dengan Gower Distance, dan sebaran klaster."""
    numeric_columns = MEMBER_NUMERIC_COLUMNS
    categorical_columns = MEMBER_CATEGORICAL_COLUMNS
    numeric, categorical, _ = member_feature_matrices(members, numeric_columns, categorical_columns)
    # K yang diuji harus K yang benar-benar dipakai aplikasi, bukan angka lain.
    _, labels, numeric_modes, categorical_modes = search_member_clusters(numeric, categorical)
    distances_to_modes = kprototypes_distances(numeric, categorical, numeric_modes, categorical_modes)
    return performance_payload(
        algorithm="K-Prototypes",
        data_type="Campuran numerik + kategorikal",
        rows=len(members),
        n_clusters=len(np.unique(labels)),
        cost=float(distances_to_modes[np.arange(len(labels)), labels].sum()),
        # Silhouette dihitung SESUDAH K ditetapkan Metode Siku, di atas matriks
        # Gower -- bukan di atas jarak pembentuk klaster. Lihat
        # `gower_silhouette` untuk alasannya.
        score=gower_silhouette(numeric, categorical, labels),
        counts=cluster_counts(labels + 1),
        cost_label="Total Cost (Dissimilarity)",
        score_label="Silhouette (Gower)",
    )


def kmeans_food_performance(foods: pd.DataFrame) -> dict:
    """Ringkasan performa klaster K-Means makanan: inertia, Calinski-Harabasz, dan Silhouette.

    Dihitung pada ruang fitur yang sama persis dengan yang membentuk klasternya.
    """
    scaled = food_cluster_features(foods)
    model = KMeans(n_clusters=FOOD_CLUSTER_COUNT, random_state=42, n_init=10)
    labels = model.fit_predict(scaled)
    return performance_payload(
        algorithm="K-Means",
        data_type="Numerik",
        rows=len(foods),
        n_clusters=len(np.unique(labels)),
        cost=float(model.inertia_),
        score=safe_calinski_harabasz(scaled, labels),
        counts=cluster_counts(assign_food_clusters(foods)),
        cost_label="Inertia",
        score_label="Calinski-Harabasz",
        extra_scores={"Silhouette": safe_silhouette(scaled, labels)},
    )


def kmodes_exercise_performance(exercises: pd.DataFrame) -> dict:
    """Ukur performa K-Modes pada data latihan: Hamming cost, rasio Hamming, dan uji Chi-Square."""
    categorical = exercise_cluster_features(exercises)
    _, labels, modes = search_exercise_clusters(categorical)
    values = categorical.astype(str).to_numpy()
    distance_matrix = categorical_pairwise_distances(values)
    return performance_payload(
        algorithm="K-Modes",
        data_type="Kategorikal",
        rows=len(exercises),
        n_clusters=len(np.unique(labels)),
        cost=kmodes_total_cost(values, labels, modes),
        # Rasio Hamming, bukan Silhouette: inilah metrik yang benar untuk data
        # kategorikal, dan ia dihitung sesudah K ditetapkan Metode Siku.
        score=hamming_separation_ratio(distance_matrix, labels),
        counts=cluster_counts(labels),
        # Chi-Square membuktikan profil tiap klaster berbeda secara statistik --
        # uji yang cocok untuk data kategorikal dan tidak bisa digantikan
        # Silhouette, karena Silhouette hanya mengukur kerapatan geometris.
        chi_square=chi_square_report(categorical, labels),
        cost_label="Hamming Cost",
        score_label="Rasio Hamming",
    )


def chi_square_report(categorical: pd.DataFrame, labels) -> pd.DataFrame:
    """Uji Chi-Square kemandirian antara label klaster dan tiap atribut.

    p < 0,05 berarti sebaran atribut itu berbeda nyata antar-klaster, yaitu
    klasternya benar-benar memisahkan sesuatu dan bukan sekadar potongan acak.
    """
    from scipy.stats import chi2_contingency

    rows = []
    for column in categorical.columns:
        table = pd.crosstab(pd.Series(labels, index=categorical.index), categorical[column])
        if table.shape[0] < 2 or table.shape[1] < 2:
            continue
        statistic, p_value, dof, _ = chi2_contingency(table)
        rows.append(
            {
                "Atribut": column,
                "Chi-Square": round(float(statistic), 3),
                "dof": int(dof),
                "p-value": float(p_value),
                "Kesimpulan": "Signifikan (p<0,05)" if p_value < 0.05 else "Tidak signifikan",
            }
        )
    return pd.DataFrame(rows)


def performance_payload(
    *,
    algorithm: str,
    data_type: str,
    rows: int,
    n_clusters: int,
    cost: float,
    score: float | None,
    counts: pd.DataFrame,
    cost_label: str,
    score_label: str,
    extra_scores: dict[str, float | None] | None = None,
    chi_square: pd.DataFrame | None = None,
) -> dict:
    """Bungkus hasil pengukuran satu algoritma jadi dict seragam siap ditampilkan."""
    return {
        "algorithm": algorithm,
        "data_type": data_type,
        "rows": rows,
        "n_clusters": n_clusters,
        "cost": round(cost, 3),
        "cost_label": cost_label,
        # Nama metriknya WAJIB ikut dibawa: ketiga algoritma dinilai dengan
        # metrik yang berbeda-beda (Calinski-Harabasz, Silhouette-Gower, Rasio
        # Hamming), dan skalanya pun berbeda. Satu label tetap akan menyesatkan.
        "score_label": score_label,
        "score": round(score, 3) if score is not None else None,
        # Metrik penilai tambahan, kalau satu angka tidak cukup menggambarkan
        # mutunya. K-Means memakainya untuk Silhouette; dua algoritma lain
        # membiarkannya kosong.
        "extra_scores": {
            nama: (round(nilai, 3) if nilai is not None else None)
            for nama, nilai in (extra_scores or {}).items()
        },
        "counts": counts,
        "chi_square": chi_square,
    }


def cluster_counts(labels) -> pd.DataFrame:
    """Tabel jumlah data per klaster, terurut menurut label."""
    counts = pd.Series(labels, name="Cluster").value_counts().sort_index()
    return counts.rename_axis("Cluster").reset_index(name="Jumlah Data")


def safe_silhouette(data, labels, metric: str = "euclidean") -> float | None:
    """Silhouette score, atau None bila jumlah klaster tidak memenuhi syarat perhitungannya."""
    unique_labels = np.unique(labels)
    if len(unique_labels) < 2 or len(unique_labels) >= len(labels):
        return None
    return float(silhouette_score(data, labels, metric=metric))


def safe_calinski_harabasz(data, labels) -> float | None:
    """Calinski-Harabasz Index, atau None bila jumlah klaster tidak memenuhi syarat.

    Disebut juga Variance Ratio Criterion: sebaran ANTAR klaster dibagi sebaran
    DI DALAM klaster, disesuaikan derajat bebasnya. Makin besar makin baik, dan
    tidak ada batas atasnya -- angkanya hanya bermakna sebagai perbandingan
    antar-K pada dataset yang sama, bukan sebagai nilai mutlak.
    """
    unique_labels = np.unique(labels)
    if len(unique_labels) < 2 or len(unique_labels) >= len(labels):
        return None
    return float(calinski_harabasz_score(data, labels))


def gower_pairwise_distances(numeric: np.ndarray, categorical: np.ndarray) -> np.ndarray:
    """Matriks jarak Gower antar seluruh pasangan baris data campuran.

    Merata-ratakan jarak ternormalisasi tiap atribut numerik dan ketidakcocokan tiap
    atribut kategorikal, sehingga sah dipakai pada data bertipe campuran.
    """
    numeric = np.asarray(numeric, dtype=float)
    categorical = np.asarray(categorical)
    rentang = numeric.max(axis=0) - numeric.min(axis=0)
    # Atribut konstan tidak membawa informasi; rentang 0 dijaga supaya tidak
    # membagi nol, dan selisihnya memang selalu 0.
    rentang[rentang == 0] = 1.0
    numerik = (np.abs(numeric[:, None, :] - numeric[None, :, :]) / rentang).sum(axis=2)
    kategorikal = (categorical[:, None, :] != categorical[None, :, :]).sum(axis=2)
    return (numerik + kategorikal) / (numeric.shape[1] + categorical.shape[1])


def gower_silhouette(numeric: np.ndarray, categorical: np.ndarray, labels: np.ndarray) -> float | None:
    """Silhouette Coefficient atas jarak Gower, untuk klaster data campuran.

    Silhouette Euclidean tidak sah pada data campuran, karena itu jaraknya diganti
    Gower lebih dulu.
    """
    sample = _evaluation_sample_index(len(numeric))
    if sample is None:
        sample = np.arange(len(numeric))
    matriks_gower = gower_pairwise_distances(numeric[sample], categorical[sample])
    return safe_silhouette(matriks_gower, np.asarray(labels)[sample], metric="precomputed")


def categorical_pairwise_distances(values: np.ndarray) -> np.ndarray:
    """Matriks jarak Hamming antar seluruh pasangan baris kategorikal."""
    return (values[:, None, :] != values[None, :, :]).sum(axis=2).astype(float)


def _food_tfidf_model(foods: pd.DataFrame) -> tuple[TfidfVectorizer, np.ndarray]:
    """Pasangan (vectorizer, tfidf_matrix) yang sudah terlatih untuk `foods`.

    Memakai ulang model yang dititipkan prepare_foods() pada foods.attrs supaya TF-IDF
    tidak dilatih ulang tiap pemanggilan; dilatih ulang di sini bila attrs-nya tidak
    cocok dengan DataFrame yang dioper.
    """
    model = foods.attrs.get("food_tfidf_model")
    if model is not None and model.get("tfidf_matrix") is not None and model["tfidf_matrix"].shape[0] == len(foods):
        return model["vectorizer"], model["tfidf_matrix"]
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(foods["CBF_Text"])
    return vectorizer, tfidf_matrix


def parse_preference_keywords(preference: str) -> list[str]:
    """Pecah input preferensi user jadi daftar kata kunci.

    User mengetik bebas, mis. "ayam, telur" atau "ayam telur". Dipisah pada
    koma maupun spasi supaya keduanya bekerja. Kata sangat pendek dibuang
    karena "di"/"a" akan cocok dengan hampir semua nama makanan.
    """
    if not preference:
        return []
    parts = re.split(r"[,;/]+|\s+", preference.strip().lower())
    return [part for part in (p.strip() for p in parts) if len(part) >= 3]


def match_food_keywords(foods: pd.DataFrame, keywords: list[str]) -> pd.Series:
    """True untuk makanan yang namanya memuat salah satu kata kunci.

    Pencocokan substring, bukan nama utuh -- itulah inti perubahannya:
    mengetik "ayam" ikut menjaring "Ayam goreng", "Sate ayam", "Soto ayam",
    tanpa user harus memilih tiap menu satu per satu.
    """
    if not keywords:
        return pd.Series(False, index=foods.index)
    names = foods["name"].fillna("").astype(str).str.lower()
    mask = pd.Series(False, index=foods.index)
    for keyword in keywords:
        mask |= names.str.contains(re.escape(keyword), regex=True, na=False)
    return mask


def build_preference_query(preference: str, categories: Iterable[str] | None = None) -> str:
    """Rakit teks kueri untuk CBF dari kategori pilihan user (dan kata kunci bebas)."""
    parts = [str(label).lower() for label in (categories or []) if label and label != OTHER_CATEGORY]
    if preference and preference.strip():
        parts.append(preference.strip().lower())
    query = " ".join(parts).strip()
    return query or "balanced protein carbohydrate"


def slot_candidate_pool(foods: pd.DataFrame, meal_slot: str) -> pd.DataFrame:
    """Kandidat yang boleh mengisi satu slot waktu makan.

    Slot camilan disaring keras dan tidak pernah dilonggarkan pada fallback mana pun;
    slot makan berat menolak kudapan manis dan jajanan yang selalu berstatus camilan.
    """
    if meal_slot == SNACK_SLOT and "Is_Snack" in foods.columns:
        return foods[foods["Is_Snack"].fillna(False).astype(bool)]
    if meal_slot in MAIN_MEAL_SLOTS and "name" in foods.columns:
        names = foods["name"].fillna("").astype(str).str.lower().str.strip()
        return foods[~names.str.contains(MAIN_MEAL_UNSUITABLE_PATTERN, regex=True, na=False)]
    return foods


def is_staple_food(foods: pd.DataFrame) -> pd.Series:
    """True untuk makanan pokok sumber karbohidrat utama."""
    names = foods["name"].fillna("").astype(str).str.lower().str.strip()
    return names.str.contains(STAPLE_PATTERN, regex=True, na=False)


def nutrition_fit_score(foods: pd.DataFrame, fitness_goal: str | None) -> pd.Series:
    """Seberapa cocok tiap menu dengan tujuan kebugaran, dihitung dari gizinya sendiri.

    Arah penilaiannya mengikuti tujuan: menurunkan berat menghargai protein padat dan
    kalori encer, menaikkan berat menghargai kalori padat, menjaga berat hanya
    menghargai kepadatan protein. Kedua sukunya dibagi pembagi tetap supaya
    besarannya sebanding.
    """
    kalori = foods["calories"].replace(0, np.nan)
    kepadatan_protein = (foods["proteins"] / kalori * 100).fillna(0)
    kepadatan_kalori = foods["calories"].fillna(0)
    goal = normalize_goal(fitness_goal) if fitness_goal else DEFAULT_FITNESS_GOAL
    if goal == "Gain Weight":
        return kepadatan_protein / 20 + kepadatan_kalori / 400
    if goal == "Lose Weight":
        return kepadatan_protein / 10 - kepadatan_kalori / 400
    return kepadatan_protein / 10


def dish_family(foods: pd.DataFrame) -> pd.Series:
    """Jenis hidangan sebuah menu: dua kata pertama namanya.

    Dipakai _rank_foods() untuk membatasi berapa banyak menu sejenis yang boleh
    menumpuk di peringkat atas.
    """
    names = foods["name"].fillna("").astype(str).str.lower().str.split()
    return names.map(lambda kata: " ".join(kata[:2]) if kata else "")


def _rank_foods(
    foods: pd.DataFrame,
    preference: str,
    categories: Iterable[str] | None,
    *,
    vectorizer: TfidfVectorizer | None = None,
    tfidf=None,
    fitness_goal: str | None = None,
) -> pd.DataFrame:
    """Urutkan menu dengan empat kunci, lalu terapkan pagar keragaman.

    Kuncinya berurutan dari yang paling tegas ke yang paling lunak:
    `_category` -> `_match` -> `_nutrition` -> `_score` (CBF).

    Alasan urutan itu dan pengukuran dampaknya: docs/catatan-desain.md bagian 6.
    """
    if vectorizer is None or tfidf is None:
        vectorizer = TfidfVectorizer(stop_words="english")
        tfidf = vectorizer.fit_transform(foods["CBF_Text"])
    query = build_preference_query(preference, categories)
    scores = cosine_similarity(vectorizer.transform([query]), tfidf).ravel()
    ranked = foods.assign(
        _score=scores,
        _category=match_food_categories(foods, categories),
        _match=match_food_keywords(foods, parse_preference_keywords(preference)),
        _nutrition=nutrition_fit_score(foods, fitness_goal),
    )
    ranked = ranked.sort_values(
        ["_category", "_match", "_nutrition", "_score"],
        ascending=[False, False, False, False],
    )

    # Pagar keragaman. Menu ke-(DISH_FAMILY_LIMIT+1) dan seterusnya dari satu
    # keluarga hidangan didorong turun. Pengurutan ulangnya stabil dan tetap
    # dipimpin _category lalu _match, sehingga kendali pengguna tidak dilangkahi.
    keluarga = dish_family(ranked)
    ranked = ranked.assign(
        _diverse=keluarga.groupby(keluarga, sort=False).cumcount() < DISH_FAMILY_LIMIT
    )
    ranked = ranked.sort_values(
        ["_category", "_match", "_diverse"],
        ascending=[False, False, False],
        kind="stable",
    )
    return ranked.drop(columns="_diverse")


def _candidate_tiers(
    pool: pd.DataFrame,
    cluster: str | None,
    *,
    cluster_first: bool = False,
) -> list[pd.DataFrame]:
    """Urutan pelonggaran filter saat slot sulit diisi.

    Kategori dan klaster boleh dilonggarkan; kelayakan camilan tidak, karena `pool`
    sudah disaring lebih dulu oleh slot_candidate_pool(). `cluster_first` dipakai
    swap, yang mensyaratkan pengganti berasal dari klaster yang sama.
    """
    pool = pool[~excluded_from_protein_role(pool, cluster)]
    in_category = pool["_category"].astype(bool)
    in_cluster = pool["Food_Cluster"] == cluster if cluster else pd.Series(True, index=pool.index)
    middle = [pool[in_cluster], pool[in_category]] if cluster_first else [pool[in_category], pool[in_cluster]]
    return [pool[in_cluster & in_category], *middle, pool]


# Kerupuk dan sejenisnya bisa sangat tinggi protein secara angka, tetapi sebagai lauk
# ia bukan sumber protein sepiring makan. Yang dilarang hanya PERANNYA: ia tetap
# boleh mengisi peran karbohidrat maupun rendah kalori.
PROTEIN_ROLES = frozenset({"B", "D"})
CRACKER_PATTERN = r"\bkerupuk\b|\bkrupuk\b|\bkeripik\b|\bkripik\b|\brempeyek\b|\bpeyek\b|\bemping\b"


def excluded_from_protein_role(foods: pd.DataFrame, cluster: str | None) -> pd.Series:
    """True untuk menu yang tidak boleh mengisi slot berperan protein."""
    if cluster not in PROTEIN_ROLES or "name" not in foods:
        return pd.Series(False, index=foods.index)
    nama = foods["name"].fillna("").astype(str).str.lower()
    return nama.str.contains(CRACKER_PATTERN, regex=True, na=False)


def split_slot_quota(slot_quota: float, item_count: int) -> list[int]:
    """Bagi kuota kalori satu slot menjadi target per item dalam bilangan bulat.

    Sisa pembagian dibagikan ke item-item pertama (metode sisa terbesar), supaya
    penjumlahan target seluruh item persis sama dengan kuota slot.
    """
    if item_count <= 0:
        return []
    quota = int(round(slot_quota))
    base, remainder = divmod(quota, item_count)
    return [base + 1 if index < remainder else base for index in range(item_count)]


def recommend_foods(
    foods: pd.DataFrame,
    nutrition: NutritionResult,
    preference: str = "",
    excluded_food_ids: Iterable[int] | None = None,
    categories: Iterable[str] | None = None,
    fitness_goal: str | None = None,
) -> dict[str, list[dict]]:
    """Susun menu harian empat slot yang totalnya persis sama dengan target kalori.

    Kuota tiap slot = target kalori harian x proporsi slot, lalu dibagi rata ke item
    di slot itu. Gramasi tiap item dihitung dengan portion_gram_for_calories() dan
    divalidasi Volumetric Sanity Check.

    `fitness_goal` menentukan SUSUNAN peran gizi tiap slot lewat meal_template(),
    bukan sekadar besaran kalorinya.
    """
    excluded = set(excluded_food_ids or [])
    vectorizer, tfidf = _food_tfidf_model(foods)
    ranked = _rank_foods(foods, preference, categories, vectorizer=vectorizer,
                         tfidf=tfidf, fitness_goal=fitness_goal)

    quotas = slot_calorie_quota(nutrition.target_calories)
    recommendations: dict[str, list[dict]] = {}
    used_ids = set(excluded)

    for meal_slot, clusters in meal_template(fitness_goal).items():
        slot_quota = quotas[meal_slot]
        item_targets = split_slot_quota(slot_quota, len(clusters))
        slot_pool = slot_candidate_pool(ranked, meal_slot)
        recommendations[meal_slot] = []

        staple_taken = False
        for cluster, item_target in zip(clusters, item_targets):
            available = slot_pool[~slot_pool["id"].isin(used_ids)]

            # Satu makanan pokok saja per slot. Kandidat non-pokok dicoba lebih dulu;
            # seluruh kandidat dipakai lagi hanya bila tidak ada yang lolos, supaya
            # kuota kalori slot tidak hilang.
            urutan = [available]
            if staple_taken and not available.empty:
                bukan_pokok = available[~is_staple_food(available)]
                if not bukan_pokok.empty:
                    urutan = [bukan_pokok, available]

            chosen = None
            for subset in urutan:
                for tier in _candidate_tiers(subset, cluster):
                    chosen = _pick_food_candidate(tier, item_target)
                    if chosen is not None:
                        break
                if chosen is not None:
                    break
            if chosen is None:
                continue

            if bool(is_staple_food(pd.DataFrame([chosen])).iloc[0]):
                staple_taken = True

            chosen["meal_slot"] = meal_slot
            chosen["slot_quota_calories"] = int(round(slot_quota))
            chosen["slot_share"] = MEAL_DISTRIBUTION[meal_slot]
            used_ids.add(int(chosen["id"]))
            recommendations[meal_slot].append(chosen)

    return recommendations


def _pick_food_candidate(candidates: pd.DataFrame, target_calories: float) -> dict | None:
    """Kandidat berperingkat tertinggi yang gramasinya lolos Volumetric Sanity Check."""
    for _, row in candidates.iterrows():
        portion = portion_gram_for_calories(target_calories, row["calories"])
        if not portion_is_realistic(portion):
            continue
        result = row.to_dict()
        result["portion_gram"] = round(portion)
        result["target_calories"] = round(target_calories)
        result["similarity_score"] = round(float(row.get("_score", 0.0)), 3)
        result["category_match"] = bool(row.get("_category", False))
        for helper in ("_score", "_category", "_match", "_nutrition"):
            result.pop(helper, None)
        return result
    return None


def swap_food(
    foods: pd.DataFrame,
    current_food: dict,
    target_calories: float,
    preference: str = "",
    excluded_food_ids: Iterable[int] | None = None,
    *,
    meal_slot: str | None = None,
    categories: Iterable[str] | None = None,
    fitness_goal: str | None = None,
) -> dict | None:
    """Ganti satu item dengan Dynamic Portion Constraint.

    Pengganti diambil dari klaster yang sama dengan item yang diganti, lalu gramasinya
    dihitung ulang terhadap kuota kalori item tersebut, sehingga total kalori harian
    tidak berubah.
    """
    excluded = {int(food_id) for food_id in (excluded_food_ids or [])}
    excluded.add(int(current_food["id"]))

    slot = meal_slot or current_food.get("meal_slot")
    pool = slot_candidate_pool(foods, slot)
    pool = pool[~pool["id"].isin(excluded)]
    if pool.empty:
        return None

    # Tujuan ikut dioper supaya penggantinya diurutkan dengan ukuran kesesuaian
    # gizi yang sama dengan saat menu itu pertama kali disusun.
    ranked = _rank_foods(pool, preference, categories, fitness_goal=fitness_goal)
    replacement = None
    for tier in _candidate_tiers(ranked, current_food.get("Food_Cluster"), cluster_first=True):
        replacement = _pick_food_candidate(tier, target_calories)
        if replacement is not None:
            break
    if replacement is None:
        return None

    # Konteks slot ikut dibawa supaya penukaran berikutnya tetap tahu slot mana
    # yang sedang diisi (dan karenanya tetap menolak makanan berat di camilan).
    replacement["meal_slot"] = slot
    for key in ("slot_quota_calories", "slot_share"):
        if current_food.get(key) is not None:
            replacement[key] = current_food[key]
    return replacement


def _exercise_pool(exercises: pd.DataFrame, body_part: str) -> pd.DataFrame:
    """Seluruh latihan untuk satu target otot, lengkap dengan kunci pengurut alat dan rating."""
    target_parts = resolve_target_body_parts(body_part)
    pool = exercises if target_parts is None else exercises[exercises["BodyPart"].isin(target_parts)]
    return pool.copy()


def exercise_cbf_scores(pool: pd.DataFrame, body_part: str, exercise_type: str,
                        experience_level: str) -> np.ndarray:
    """Skor Content-Based Filtering tiap latihan di kolam terhadap kueri pengguna.

    TF-IDF dilatih pada KOLAM, bukan seluruh korpus, supaya IDF-nya mencerminkan
    kandidat yang benar-benar bersaing. Kueri dirakit dari target otot, jenis latihan,
    dan level; alat dan tujuan kebugaran tidak ikut (docs/catatan-desain.md bagian 5).
    """
    if pool.empty:
        return np.zeros(0)
    vectorizer = TfidfVectorizer(stop_words="english")
    matriks = vectorizer.fit_transform(pool["CBF_Text"])
    kueri = f"{body_part} {exercise_type} {experience_level}".strip()
    return cosine_similarity(vectorizer.transform([kueri]), matriks).ravel()


def _rank_exercise_candidates(pool: pd.DataFrame, experience_level: str,
                              used_equipment: set, used_clusters: set,
                              *, body_part: str = "", exercise_type: str = "") -> pd.DataFrame:
    """Urutkan kandidat latihan dengan empat kunci, dari yang paling tegas ke paling lunak.

        _cluster_fresh   -> klaster K-Modes yang belum terwakili didahulukan
        _equipment_fresh -> alat yang belum terpakai didahulukan
        _equipment_rank  -> prioritas alat menurut level pengalaman
        _cbf             -> cosine similarity Content-Based Filtering

    CBF sengaja menjadi kunci terakhir: struktur menyaring lebih dulu, CBF memutuskan
    di dalam sisanya. Klaster dipakai sebagai pengurut, bukan penyaring keras.
    """
    prioritas = EQUIPMENT_PRIORITY[experience_level]
    peringkat = {alat: urutan for urutan, alat in enumerate(prioritas)}
    kolom_klaster = pool["Exercise_Cluster"] if "Exercise_Cluster" in pool else pd.Series(
        -1, index=pool.index
    )
    return pool.assign(
        _cluster_fresh=(~kolom_klaster.isin(used_clusters)).astype(int),
        _equipment_fresh=(~pool["Equipment"].isin(used_equipment)).astype(int),
        _equipment_rank=pool["Equipment"].map(lambda alat: peringkat.get(alat, len(prioritas))),
        _cbf=exercise_cbf_scores(pool, body_part, exercise_type, experience_level),
    ).sort_values(
        ["_cluster_fresh", "_equipment_fresh", "_equipment_rank", "_cbf"],
        ascending=[False, False, True, False],
    )


def _scale_type_plan(fitness_goal: str, limit: int) -> list[tuple[str, int]]:
    """Kuota tiap jenis latihan untuk jumlah latihan yang diminta."""
    plan = EXERCISE_TYPE_PLAN[normalize_goal(fitness_goal)]
    total = sum(jumlah for _, jumlah in plan)
    return [(jenis, max(1, round(jumlah * limit / total))) for jenis, jumlah in plan]


def recommend_exercises(
    exercises: pd.DataFrame,
    *,
    body_part: str,
    experience_level: str,
    fitness_goal: str,
    limit: int = 5,
) -> pd.DataFrame:
    """Susun program latihan dari target otot dan jumlah yang diminta.

    Jenis latihan ditentukan tujuan lewat EXERCISE_TYPE_PLAN dan prioritas alat
    ditentukan level lewat EQUIPMENT_PRIORITY; keduanya bukan masukan pengguna.
    Tiap kuota jenis menaiki EXERCISE_LEVEL_LADDER sampai terpenuhi, dan latihan yang
    diambil dari lapis di atas level pengguna ditandai pada NEEDS_SUPERVISION_COLUMN.
    """
    pool = _exercise_pool(exercises, body_part)
    params = TRAINING_PARAMETERS[(normalize_goal(fitness_goal), experience_level)]
    if pool.empty:
        kosong = pool.assign(Similarity=pd.Series(dtype=float))
        kosong[NEEDS_SUPERVISION_COLUMN] = pd.Series(dtype=bool)
        for key, value in params.items():
            kosong[key] = value
        return kosong

    tangga = EXERCISE_LEVEL_LADDER[experience_level]
    terpilih: list[pd.Series] = []
    judul_dipakai: set[str] = set()
    alat_dipakai: set[str] = set()
    klaster_dipakai: set = set()

    def ambil(kandidat: pd.DataFrame, jumlah: int, lapis: int, jenis: str = "") -> int:
        kandidat = kandidat[~kandidat["Title"].astype(str).isin(judul_dipakai)]
        if kandidat.empty or jumlah <= 0:
            return 0
        terurut = _rank_exercise_candidates(
            kandidat, experience_level, alat_dipakai, klaster_dipakai,
            body_part=body_part, exercise_type=jenis,
        )
        diambil = 0
        for _, baris in terurut.head(jumlah).iterrows():
            catatan = baris.copy()
            catatan[NEEDS_SUPERVISION_COLUMN] = lapis > 1
            terpilih.append(catatan)
            judul_dipakai.add(str(baris["Title"]))
            alat_dipakai.add(baris["Equipment"])
            if "Exercise_Cluster" in baris:
                klaster_dipakai.add(baris["Exercise_Cluster"])
            diambil += 1
        return diambil

    for jenis, jumlah in _scale_type_plan(fitness_goal, limit):
        sisa = jumlah
        for lapis, level_set in enumerate(tangga, start=1):
            if sisa <= 0:
                break
            sisa -= ambil(pool[pool["Level"].isin(level_set) & (pool["Type"] == jenis)],
                          sisa, lapis, jenis)

    # Kuota yang tak terpenuhi jatuh ke sisa kolam, jenis apa pun, tetap menaiki
    # tangga level yang sama.
    for lapis, level_set in enumerate(tangga, start=1):
        if len(terpilih) >= limit:
            break
        ambil(pool[pool["Level"].isin(level_set)], limit - len(terpilih), lapis)

    selected = pd.DataFrame(terpilih[:limit])
    if selected.empty:
        selected = pool.iloc[0:0].assign(Similarity=pd.Series(dtype=float))
        selected[NEEDS_SUPERVISION_COLUMN] = pd.Series(dtype=bool)
    else:
        bantu = ("_cluster_fresh", "_equipment_fresh", "_equipment_rank", "_cbf")
        # Skor CBF dipertahankan sebagai kolom Similarity -- itulah nilai yang
        # benar-benar dipakai memeringkat di dalam tiap kuota jenis.
        selected["Similarity"] = selected["_cbf"].round(3) if "_cbf" in selected else pd.NA
        selected = selected.drop(columns=[k for k in bantu if k in selected])
    for key, value in params.items():
        selected[key] = value
    return selected


def resolve_target_body_parts(body_part: str) -> set[str] | None:
    """Terjemahkan pilihan target otot jadi himpunan BodyPart di dataset; None berarti tanpa batasan."""
    if body_part == "Any":
        return None
    return TARGET_MUSCLE_GROUPS.get(body_part, {body_part})


def switch_exercise(
    exercises: pd.DataFrame,
    current_exercise: dict,
    current_recommendations: pd.DataFrame,
    filters: dict,
) -> dict | None:
    """Ganti satu latihan tanpa merusak komposisi program.

    Jenis latihan yang diganti dipertahankan, dan pengganti diambil dari klaster yang
    sama lebih dulu sebelum dilonggarkan. Alat serta klaster yang sedang dipakai
    program lain ikut dihindari.
    """
    experience_level = filters.get("experience_level", "Beginner")
    fitness_goal = filters.get("fitness_goal", "Maintain Weight")
    body_part = filters.get("body_part", "Any")

    pool = _exercise_pool(exercises, body_part)
    if pool.empty:
        return None

    current_title = str(current_exercise.get("Title", ""))
    current_type = str(current_exercise.get("Type", ""))
    selected_titles = {
        str(title)
        for title in current_recommendations.get("Title", pd.Series(dtype=str)).tolist()
    }
    excluded_titles = {str(title) for title in filters.get("excluded_titles", [])}
    pool = pool[~pool["Title"].astype(str).isin(selected_titles | excluded_titles | {current_title})]
    if pool.empty:
        return None

    # Alat dan klaster yang sedang dipakai program lain ikut dihindari supaya
    # penggantian tidak membuat seluruh program menyempit ke satu jenis.
    alat_dipakai = set(current_recommendations.get("Equipment", pd.Series(dtype=str)).tolist())
    alat_dipakai.discard(current_exercise.get("Equipment"))
    klaster_dipakai = set(
        current_recommendations.get("Exercise_Cluster", pd.Series(dtype=object)).tolist()
    )
    klaster_dipakai.discard(current_exercise.get("Exercise_Cluster"))

    # Tangga pelonggaran: jenis yang sama pada level sendiri dulu, lalu jenis
    # yang sama pada level di atasnya, baru jenis apa pun.
    tangga = EXERCISE_LEVEL_LADDER[experience_level]
    lapisan = []
    if current_type:
        lapisan += [(pool[pool["Level"].isin(lv) & (pool["Type"] == current_type)], urutan)
                    for urutan, lv in enumerate(tangga, start=1)]
    lapisan += [(pool[pool["Level"].isin(lv)], urutan) for urutan, lv in enumerate(tangga, start=1)]

    for kandidat, lapis in lapisan:
        if kandidat.empty:
            continue
        baris = _rank_exercise_candidates(
            kandidat, experience_level, alat_dipakai, klaster_dipakai,
            body_part=body_part, exercise_type=current_type,
        ).iloc[0]
        skor = float(baris.get("_cbf", 0.0) or 0.0)
        replacement = baris.drop(
            labels=["_cluster_fresh", "_equipment_fresh", "_equipment_rank", "_cbf"],
            errors="ignore",
        ).to_dict()
        replacement[NEEDS_SUPERVISION_COLUMN] = lapis > 1
        replacement.update(TRAINING_PARAMETERS[(normalize_goal(fitness_goal), experience_level)])
        replacement["Similarity"] = round(skor, 3)
        return replacement
    return None


def profile_payload(nutrition: NutritionResult, **profile) -> dict:
    """Gabungkan data profil dan hasil perhitungan gizi jadi satu dict siap disimpan."""
    payload = dict(profile)
    payload.update(asdict(nutrition))
    return payload
