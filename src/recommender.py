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


# Pola distribusi energi harian yang lazim dipakai dalam penyelenggaraan makanan.
# Empat slot, dan jumlah proporsinya PERSIS 1,0 -- itu yang membuat total kuota
# seluruh slot selalu setara dengan kebutuhan energi harian pengguna. Contoh untuk
# kebutuhan 2.000 kkal: 500 / 600 / 400 / 500 kkal.
MEAL_DISTRIBUTION = {
    "Breakfast": 0.25,
    "Lunch": 0.30,
    "Snack": 0.20,
    "Dinner": 0.25,
}

# Isi tiap slot dinyatakan sebagai daftar klaster K-Means makanan
# (A = tinggi karbohidrat, B = tinggi protein, C = rendah kalori). Panjang daftar
# = jumlah item pada slot itu, dan kuota slot dibagi rata ke tiap item supaya
# penjumlahan seluruh slot tetap sama dengan kebutuhan energi harian.
MEAL_TEMPLATE = {
    "Breakfast": ["A", "B"],
    "Lunch": ["A", "B", "C"],
    # Camilan hanya SATU item. Dua item membuat "camilan" terbaca seperti waktu
    # makan keempat, dan kuota 20% yang dibagi dua menghasilkan dua porsi kecil
    # yang justru lebih merepotkan daripada satu porsi utuh.
    "Snack": ["C"],
    "Dinner": ["B", "C"],
}

SNACK_SLOT = "Snack"
BREAKFAST_SLOT = "Breakfast"

# Makanan pokok sumber karbohidrat utama. Dalam SATU slot hanya boleh ada satu.
# Tanpa aturan ini, memilih preferensi "Nasi" membuat slot makan siang berisi
# "Nasi" + "Nasi goreng" sekaligus -- dua kali makanan pokok yang sama, dan
# secara gizi maupun akal sehat itu bukan susunan sepiring makan.
STAPLE_PATTERN = (
    r"^nasi\b|\bnasi\b|^bubur\b|\bbubur\b|^lontong\b|\bketupat\b|^ketupat\b"
    r"|^mie\b|^mi\b|\bmie\b|^bihun\b|\bbihun\b|^kwetiau\b|^misoa\b|^makaroni\b"
    r"|^spaghetti\b|^vermicelli\b|^soun\b|^papeda\b|^tiwul\b|^oyek\b|^jagung titi\b"
    r"|^roti\b|^lontong\b|^buras\b|^bacang\b|^lemper\b|^pulut\b|^ketan\b|^lopis\b"
    r"|^rasbi\b|^rasi\b|^kapurung\b|^intip\b"
)

# Bentuk sajian yang tidak pantas jadi menu SARAPAN walaupun sah sebagai
# makanan: gula-gula, jajanan manis pekat, dan gorengan kering berbasis kerupuk.
# Sarapan tetap boleh berupa nasi uduk, bubur, roti, telur, mie, atau lontong --
# yang disingkirkan hanya yang lazimnya dimakan sebagai camilan sore atau oleh-
# oleh, bukan pembuka hari.
BREAKFAST_UNSUITABLE_PATTERN = (
    r"^permen\b|\bdodol\b|^jenang\b|^wajik\b|^wajit\b|^geplak\b|^yangko\b"
    r"|\bes krim\b|^es mambo\b|^es sirup\b|^coklat\b|^choklat\b|\bcoklat batang\b"
    # Tidak di-anchor ke awal nama: bentuknya sering muncul di belakang, mis.
    # "Kacang Tanah rempeyek" dan "Emping (kerupuk melinjo)".
    r"|\bkerupuk\b|\bkrupuk\b|\bkeripik\b|\bkripik\b|\bemping\b|\brempeyek\b|^brondong\b"
    r"|^noga\b|^enting-enting\b|^widaran\b|^suwir-suwir\b|^sale\b|^kwaci\b"
    r"|^manisan\b|^selai\b|^jam selai\b|^koya\b|^biskuit\b|^slondok\b|^rengginang\b"
)

# Volumetric Sanity Check: gramasi hasil konversi kalori harus berada di rentang
# ini. Di bawah 50 g porsinya terlalu kecil untuk memicu rasa kenyang, di atas
# 450 g melampaui kapasitas lambung yang nyaman untuk SATU jenis item. Item yang
# gagal dicek didiskualifikasi dan sistem lanjut ke peringkat cosine similarity
# berikutnya.
MIN_PORTION_GRAM = 50
MAX_PORTION_GRAM = 450

# --------------------------------------------------------------------------- #
# Penetapan jumlah klaster
# --------------------------------------------------------------------------- #
# Jumlah klaster TIDAK ditulis tetap di kode, melainkan ditetapkan otomatis
# dengan METODE SIKU (Elbow Method) atas fungsi biaya algoritmanya sendiri:
# Hamming Cost berbobot untuk K-Modes dan Total Cost gabungan untuk
# K-Prototypes. Titik sikunya dicari secara terukur, bukan ditaksir dari grafik
# (lihat `elbow_cluster_count`), sehingga K di notebook pengujian dan K di
# aplikasi tidak mungkin berbeda.
#
# ELBOW DIPAKAI SENDIRIAN UNTUK MEMILIH K. Metrik mutu -- Calinski-Harabasz
# (K-Means), Silhouette dengan Gower Distance (K-Prototypes), dan Rasio Hamming
# (K-Modes) -- dihitung SETELAH K ditetapkan, sebagai penilaian hasil. Kalau
# sebuah metrik ikut memilih K, ia otomatis terlihat bagus: K-nya memang dipilih
# supaya metrik itu setinggi mungkin. Memisahkan pemilih dari penilai membuat
# angka yang dilaporkan bermakna sebagai bukti.
CLUSTER_SEARCH_RANGE = range(2, 11)

# Metrik evaluasi berbasis jarak butuh matriks antar-semua-pasangan (n x n). Di
# atas ambang ini matriksnya dihitung pada sampel deterministik supaya kebutuhan
# memorinya tidak tumbuh kuadratik saat dataset bertambah; hasilnya tetap sama
# di setiap proses karena sampelnya sama.
EVALUATION_SAMPLE_LIMIT = 2000

# K-Means makanan SENGAJA tetap 3 dan tidak ikut ditetapkan Metode Siku: ketiga
# klaster dipetakan ke peran gizi A (tinggi karbohidrat), B (tinggi protein),
# dan C (rendah kalori) yang dipakai MEAL_TEMPLATE untuk menyusun slot makan.
# Jumlah klaster lain akan membuat pemetaan itu kehilangan arti.
#
# Perlu disebut terus terang: pada data yang sudah disiapkan aplikasi, siku
# kurva WCSS jatuh di K = 5 (jarak ke garis 0,259), disusul K = 4 (0,247) dan
# K = 3 (0,214). Kurvanya landai sehingga ketiganya berdekatan, tetapi K = 3
# BUKAN titik siku. Notebook pengujian menampilkan kurva itu apa adanya dan
# menyatakan bahwa K = 3 dipilih karena kebutuhan struktural MEAL_TEMPLATE,
# lalu mutunya diuji pada K = 3 dengan Calinski-Harabasz Index.
FOOD_CLUSTER_COUNT = 3

# Berapa banyak titik awal yang diadu sebelum sebuah klaster ditetapkan.
# Inisialisasi linspace SELALU ikut diadu, lalu ditambah seed 0..N-1, sehingga
# hasilnya tetap deterministik (tidak ada seed yang diundi saat aplikasi jalan)
# tapi tidak lagi bergantung pada satu tebakan awal.
#
# Pemenangnya dipilih dengan FUNGSI BIAYA algoritmanya sendiri -- ukuran yang
# sama persis dengan yang dipakai Metode Siku. Karena pemilih titik awal dan
# pemilih K memakai satu ukuran, menambah percobaan hanya bisa menurunkan biaya
# di setiap K; ia tidak pernah bisa memperburuk kurva sikunya.
EXERCISE_INIT_ATTEMPTS = 10
MEMBER_INIT_ATTEMPTS = 20

# --------------------------------------------------------------------------- #
# Kelayakan menu
# --------------------------------------------------------------------------- #
# Dulu kelayakan ditentukan DAFTAR IZIN: sebuah menu hanya boleh direkomendasikan
# kalau namanya memuat salah satu dari 46 kata masak ("nasi", "goreng", "rebus",
# ...). Aturan itu membuang 1.187 dari 1.586 baris, dan 684 di antaranya bukan
# bahan mentah sama sekali -- "abon", "bakwan", "bacang", "buras", "buntil",
# "bika ambon", "bakpia", "barongko" hilang hanya karena penulisnya tidak
# menyebut cara masak di nama menunya.
#
# Sekarang dibalik menjadi DAFTAR TOLAK: sebuah menu diterima KECUALI namanya
# menunjukkan ia bukan hidangan siap santap. Arah kesalahannya ikut berbalik --
# dulu risikonya membuang makanan jadi, sekarang risikonya meloloskan bahan --
# jadi daftar di bawah disusun dari pemeriksaan seluruh isi dataset, bukan
# ditebak.

# 1. BUKAN PANGAN MANUSIA. Ini soal keamanan, bukan selera, dan tidak boleh
#    dilonggarkan lewat filter kategori mana pun.
NOT_HUMAN_FOOD_PATTERN = (
    # Beracun. Tempe bongkrek adalah penyebab keracunan massal paling terkenal
    # di Indonesia (asam bongkrek, tidak hilang oleh pemanasan). Gadung
    # mengandung sianida dan dioskorin, hanya aman setelah pengolahan panjang
    # yang tidak tercermin di nama barisnya.
    r"\bbongkrek\b|\bgadung\b|\bgadeng\b|\bpicung\b"
    # Pakan ternak & ampas industri.
    r"|\bbungkil\b|\bampas\b|\bdedak\b|\bkatul\b|\bkathul\b|\bonggok\b|\bpollard\b"
    # Minuman beralkohol.
    r"|^bir\b|\bbir \(|\bbrem\b|\btuak\b|\barak\b|\balkohol\b|\bciu\b"
    # Obat, jamu, dan sediaan medis.
    r"|\bjamu\b|\boralit\b|sirup (?:batuk|obat)|\bparasetamol\b|\bpapasetamol\b"
    # Susu formula & ASI.
    r"|breastmilk|\basi\b|susu formula"
    # --- Ditambahkan setelah penyisiran kelayakan atas 845 kandidat. ---
    # Organ dengan bahaya kesehatan nyata, bukan sekadar tidak disukai: otak
    # sangat tinggi kolesterol, ginjal menumpuk logam berat dan purin.
    #
    # Batasnya sengaja ditarik pada BAHAYA, bukan pada selera gizi. Jeroan
    # sebagai hidangan tetap boleh -- soto jeroan, ampela, usus, dan hati
    # adalah lauk warteg sehari-hari yang halal dan lazim; membuangnya berarti
    # menilai pola makan pengguna, bukan menjaga keamanannya. Penyisiran
    # kelayakan sempat menandai soto jeroan, lalu pemeriksa pembanding
    # membantahnya dengan alasan itu, dan bantahan itu diterima.
    r"|^otak\b|\botak masakan\b|\bginjal\b"
    # Sarang burung walet: tonik mewah, bukan komponen makan harian.
    r"|^sarang burung"
)

# Non-halal & satwa dilindungi yang namanya tidak menyebut hewannya secara
# langsung, jadi tidak tertangkap EXCLUDED_FOOD_PATTERN. Semuanya hasil
# penyisiran kelayakan, bukan tebakan:
#   ham, leverwost  -> olahan daging babi
#   tinoransak      -> hidangan Minahasa yang bentuk bakunya babi
#   kura-kura, punai, telur burung sawah -> satwa liar/dilindungi
#   belida          -> ikan Chitala spp., dilindungi undang-undang
PROTECTED_OR_HARAM_DISH_PATTERN = (
    r"^ham$|\bleverwost\b|\bsosis hati\b|\btinoransak\b"
    r"|\bkura-kura\b|\bpunai\b|\btelur burung sawah\b|\bbelida\b"
)

# 2. BAHAN, BUMBU, DAN OLAHAN SETENGAH JADI -- bukan hidangan yang disajikan.
# Kata "segar" SENGAJA dikeluarkan dari daftar ini dan ditangani terpisah lewat
# RAW_FRESH_PATTERN di bawah. Alasannya: pada 284 baris TKPI yang memuat kata
# itu, sebagian besar memang bahan mentah (daun, cabai, daging babi, jeroan),
# tetapi 26 di antaranya buah siap santap -- "Mangga segar", "Melon segar",
# "Apel malang segar". Menyamaratakan keduanya membuang buah yang justru paling
# pantas direkomendasikan aplikasi gizi.
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
    # Mete adalah BIJI jambu monyet, bukan buahnya. Tanpa aturan ini ia lolos
    # lewat kata "jambu" pada FRESH_FRUIT_PATTERN, padahal bentuk mentahnya
    # (616 kkal, 48 g lemak per 100 g) adalah bahan, sama seperti kacang utuh
    # lain yang sudah dikecualikan lewat "^kacang [a-z]+$".
    r"|\bbiji jambu monyet\b|\bkacang mete\b|\bkacang mede\b"
)

# 4. Kewajaran nilai gizi. Dataset TKPI memuat galat nyata yang selama ini
#    tersembunyi karena barisnya toh tidak lolos daftar izin: "Pilus" tercatat
#    647 g karbohidrat per 100 g, "Bubur" 60 g lemak tapi hanya 60 kkal.
#    Nilai seperti itu merusak Persamaan Konversi Kalori ke Gramasi -- porsinya
#    ikut meleset berlipat -- jadi barisnya tidak boleh direkomendasikan.
NUTRITION_MASS_LIMIT_GRAM = 100
NUTRITION_ENERGY_TOLERANCE = 0.25

# Bahan yang tidak layak direkomendasikan ke pengguna aplikasi ini, dua alasan:
#
# 1. Non-halal. Dataset komposisi pangan Indonesia memuat babi dan anjing;
#    mayoritas pengguna sasaran tidak mengonsumsinya, dan menawarkannya sebagai
#    "rekomendasi" adalah kegagalan produk, bukan sekadar selera.
# 2. Satwa dilindungi. Penyu termasuk satwa yang dilindungi undang-undang di
#    Indonesia, jadi aplikasi tidak boleh menganjurkan konsumsinya sama sekali.
#
# Disaring di prepare_foods, sebelum klasterisasi maupun TF-IDF, supaya bahan
# ini tidak pernah muncul lewat jalur mana pun -- rekomendasi, tukar menu,
# maupun filter kategori.
# Beberapa bahan NABATI memakai nama hewan dan tidak boleh ikut tersaring:
# "kacang babi" adalah kacang koro/fava, "jambu monyet" adalah jambu mete, dan
# "pepare ular" adalah sayur. Karena itu "babi" memakai negative lookbehind
# untuk "kacang ", sedangkan "monyet" dan "ular" sengaja TIDAK didaftarkan
# sama sekali (dagingnya memang tidak ada di dataset ini).
EXCLUDED_FOOD_PATTERN = (
    r"(?:(?<!kacang )\b(?:babi|khinzir|celeng|bagong|b2)\b"
    r"|\b(?:anjing|rw|penyu|tuntong|labi-labi|biawak|kelelawar|paniki|kalong|"
    r"codot|tikus|katak|kodok|bekicot)\b)"
)

# --------------------------------------------------------------------------- #
# Kelayakan slot camilan
# --------------------------------------------------------------------------- #
# Slot camilan sebelumnya hanya dibatasi klaster kalori, sehingga "nasi",
# "mie ayam", dan hidangan berat lain tetap muncul -- cukup dengan porsi yang
# dikecilkan. Porsi kecil TIDAK membuat sepiring nasi menjadi camilan, jadi
# kelayakannya sekarang ditentukan bentuk sajiannya, bukan kalorinya.

# Bentuk sajian yang selalu camilan, apa pun kata lain di namanya. Dipakai
# lebih dulu supaya "kerupuk mie kuning goreng" tidak tertolak oleh kata "mie".
SNACK_ALWAYS_PATTERN = (
    r"\b(?:kerupuk|keripik|kripik|rempeyek|peyek|emping|getuk|kecimpring|renggi|intip)\b"
)

# Buah yang dimakan sebagai buah. Dipakai dua kali: sebagai kategori filter
# ("Buah") dan sebagai penanda kelayakan camilan.
FRUIT_PATTERN = (
    r"\b(?:alpukat|alpokat|anggur|apel|arbei|belimbing|cempedak|cerme|duku|durian|"
    r"duwet|jambu|jeruk|kedondong|kelengkeng|kepel|kesemek|kokosan|kurma|langsat|"
    r"mangga|manggis|markisa|melon|menteng|nanas|nangka|pepaya|rambutan|salak|sawo|"
    r"semangka|sirsak|srikaya|sukun|talok|kersen|cimplukan|matuwa|jambu biji|"
    r"buah naga|buah nona|buah merah|strawberry|stroberi|alpuket)\b"
)

# Penanda bahan mentah yang HANYA berlaku kalau bukan buah. Dipisahkan dari
# INGREDIENT_PATTERN karena "segar" punya dua arti di dataset TKPI:
#
#   "Sapi daging gemuk segar", "Udang galah segar", "Daun katuk segar"
#       -> bahan mentah, wajib dimasak dulu, tidak boleh direkomendasikan.
#   "Mangga segar", "Pisang kepok segar", "Apel malang segar"
#       -> justru bentuk siap santapnya, dan camilan paling sehat yang bisa
#          ditawarkan aplikasi gizi.
#
# Bug yang diperbaiki: sebelumnya "segar" ada di dalam INGREDIENT_PATTERN,
# sehingga 30 buah segar terbuang diam-diam. Cacatnya tidak terlihat selama
# pengujian memakai data/food_nutrition.csv, karena berkas itu memuat nama yang
# sudah dipendekkan ("Mangga"), sedangkan tabel database yang dipakai aplikasi
# menyimpan nama asli TKPI ("Mangga segar").
RAW_FRESH_PATTERN = r"\bsegar\b"

# Hasil penyisiran kelayakan seluruh 866 nama menu oleh 12 peninjau, lalu setiap
# tuduhan diadu dengan pembantah adversarial yang tugasnya MEMBANTAH. Dari 65
# tuduhan, 51 gugur dan 14 bertahan -- yang di bawah ini.
#
# Pembantahan itu bagian penting metodenya: yang gugur termasuk Kluwek, Petis,
# Taoco, Peterseli, Coklat bubuk, dan Gelatine, karena semuanya ternyata dipakai
# sebagai komponen hidangan Indonesia yang sah. Tanpa lapis pembantah, keenamnya
# akan ikut terhapus.
#
#   Minuman, bukan pengisi slot makan:
#       Es Sirup, Lemonade, Lemon Squasih, Markisa squash, Markisa squash BD
#   Bahan/pemanis yang tidak disantap sendirian:
#       Kopi bagian yang larut, Melase, Setrup sirup
#   Serealia mentah yang wajib ditanak dulu:
#       Jagung kuning/putih giling, jagung kuning/putih pipil lama, Jali, Jawawut
#
# Sengaja anchored ketat. "Jagung pipil BARU" (jagung muda, bisa direbus) tetap
# lolos, begitu juga Es krim, Es Mambo, Nasi jagung, Jagung rebus, dan Jagung
# titi -- pola ini diuji tidak menyentuh satu pun di antaranya.
NOT_A_MEAL_PATTERN = (
    r"^es sirup$|^lemonade$|\bsquash\b|\bsquasih\b|^setrup\b|^kopi\b|^melase$"
    r"|^jali$|^jawawut$"
    r"|^jagung (?:kuning|putih) giling$|^jagung (?:kuning|putih) pipil lama$"
    # Bumbu, pasta penyedap, dan bahan pelengkap yang sempat lolos. Penyisiran
    # otomatis sebelumnya membantah sebagian di antaranya dengan alasan "komponen
    # sah hidangan Indonesia" -- memang benar sebagai KOMPONEN, tetapi tidak satu
    # pun disantap sendirian dalam porsi gram sebagai menu makan, dan itulah yang
    # dilakukan aplikasi ini terhadap setiap baris yang lolos.
    #   petis        : pasta udang/ikan, pelengkap rujak & tahu petis
    #   taoco/tauji  : pasta kedelai fermentasi, bumbu masakan
    #   prey         : bawang daun, aromatik
    #   kepala susu  : krim, bahan olahan susu
    #   asam masak   : asam jawa, 62,5 g karbohidrat/100 g -- pemberi rasa asam
    r"|^petis\b|^taoco\b|^tauco\b|^tauji\b|^prey\b|^kepala susu\b|^asam masak\b"
    # Rempah, herba, dan bahan yang hanya dipakai sebagai pelengkap. Anchor-nya
    # ketat ke seluruh nama supaya hidangan turunannya tetap selamat:
    # "Bagea kenari", "kue bolu kenari", "Pindang kenari masakan",
    # "Enting-enting wijen", "Coklat Manis batang" tidak ikut tersaring.
    r"|^kluwek\b|^peterseli\b|^kucai\b|^wijen$|^kenari$|^gelatine?$|^coklat bubuk$"
    # Sayur dan lalapan MENTAH. Semuanya memang dimakan di Indonesia, tetapi
    # sebagai pendamping nasi dalam beberapa lembar -- bukan hidangan yang
    # disantap sendirian 200-400 g seperti yang dihitung Persamaan Konversi
    # Kalori ke Gramasi. INGREDIENT_PATTERN sudah memuat bentuk telanjangnya
    # ("^terong$", "^paria$", "^kool$"), yang ditambahkan di sini varian yang
    # lolos karena namanya bersambung.
    r"|^jotang\b|^krokot\b|^kerokot\b|^tespong\b|^susupan\b|^tekokak\b|^leunca\b"
    r"|^karawila\b|^rimbang\b|^putri malu\b|^purundawa\b|^andewi\b|^baligo\b|^erbis\b"
    # Anchor ke SELURUH nama (atau nama + kurung penjelas), bukan sekadar kata
    # pertama: "Paria Putih kukus", "Gambas lodeh", dan "Parede baleh masakan"
    # adalah hidangan matang dan harus tetap lolos.
    r"|^kundur$|^paria$|^paria \(|^pe-?cay$|^terung panjang$|^pepaya muda$"
    r"|^mostarda\b|^kool\b|^gambas$|^gambas \(|^kentang hitam$|^bit$"
)

# Buah yang tetap diterima walaupun namanya memuat "segar". Selain FRUIT_PATTERN,
# ditambahkan buah yang benar-benar ada di dataset tetapi belum terdaftar.
# Bentuk NON-buah dari tanaman yang sama tidak ikut lolos karena masih tertangkap
# aturan lain: "Jantung Pisang" oleh FRUIT_AS_INGREDIENT_PATTERN, "Bonggol
# Pisang" oleh ^bonggol, "Tepung Pisang" oleh \btepung\b.
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
    # Buah segar adalah camilan yang paling pantas direkomendasikan aplikasi
    # gizi, jadi ikut dianggap layak mengisi slot camilan.
    #
    # Dipakai FRESH_FRUIT_PATTERN, bukan FRUIT_PATTERN, supaya buah yang baru
    # dikenali juga ikut -- Matoa, Kawista, Lontar, Terung belanda, dan buah
    # bernama "Buah ..." lainnya. Sebelumnya buah-buah itu lolos saringan
    # kelayakan tetapi tetap tidak pernah muncul di slot camilan, jadi
    # penambahannya tidak terasa oleh pengguna.
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
# dipakai untuk memisahkan bahan yang namanya bertumpuk: "telur ayam dadar"
# adalah telur, bukan daging ayam.
#
# Memilih satu kategori otomatis mencakup SELURUH menu yang berkaitan --
# memilih "Ayam" berarti ayam goreng, ayam ampela, ayam taliwang, dan seterusnya,
# tanpa user perlu menandai menunya satu per satu.
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
    "Telur": (r"\b(?:telur|dadar)\b", None),
    "Tahu, Tempe & Oncom": (r"\b(?:tahu|tempe|oncom)\b", None),
    "Sayuran": (
        r"\b(?:sayur|sayuran|bayam|kangkung|buncis|wortel|terong|terung|taoge|toge|selada|"
        r"paria|cap cai|karedok|gado-gado|gado|urap|pecel|asinan|ketoprak|pakis|kool|lebui|"
        r"terubuk|umbut|kohu-kohu|ndusuk|garu|anyang|ares|kaparende|lamtoro|jengkol)\b",
        None,
    ),
    "Kacang-kacangan": (r"\bkacang\b", None),
    "Nasi & Olahan Beras": (
        r"\b(?:nasi|bubur|lontong|intip|gendar|tim|pundut|ketupat|renggi)\b",
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

# Pilihan preferensi yang ditawarkan ke pengguna, dipersempit ke SUMBER PROTEIN.
#
# Sebelumnya keenam belas kategori disodorkan sekaligus, termasuk yang sebenarnya
# bukan pilihan bermakna bagi pengguna: "Nasi & Olahan Beras", "Mie & Bihun",
# dan "Kerupuk & Keripik" adalah sumber karbohidrat atau pelengkap yang memang
# sudah diatur MEAL_TEMPLATE lewat klaster A/B/C. Yang benar-benar ingin dipilih
# pengguna adalah lauknya -- itulah yang menentukan rasa sebuah menu.
#
# Kunci = label yang tampil, nilai = nama kategori di FOOD_CATEGORIES.
PROTEIN_PREFERENCE_CATEGORIES: dict[str, str] = {
    "Ayam": "Ayam",
    "Daging Sapi": "Daging Sapi",
    "Daging Kambing": "Daging Kambing",
    "Telur": "Telur",
    "Ikan & Seafood": "Ikan & Seafood",
    "Olahan Kedelai": "Tahu, Tempe & Oncom",
    "Kacang-kacangan": "Kacang-kacangan",
    "Sayur": "Sayuran",
}


def protein_preference_options(foods: pd.DataFrame, meal_slot: str | None = None) -> dict[str, str]:
    """Label preferensi yang benar-benar punya menu di dataset (atau di slot itu)."""
    tersedia = set(available_food_categories(foods, meal_slot=meal_slot))
    return {
        label: kategori
        for label, kategori in PROTEIN_PREFERENCE_CATEGORIES.items()
        if kategori in tersedia
    }

IMAGE_CHECK_MAX_WORKERS = 20

LEVEL_ALLOWLIST = {
    "Beginner": {"Beginner"},
    "Intermediate": {"Beginner", "Intermediate"},
    "Expert": {"Beginner", "Intermediate", "Expert"},
}

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
# Compendium of Physical Activities. Dipakai untuk menaksir kalori yang terbakar
# saat pengguna mengklaim sebuah latihan sudah dikerjakan:
#
#     kkal = MET x 3,5 x berat badan (kg) / 200 x durasi (menit)
#
# Hasilnya SELALU perkiraan -- tidak ada sensor detak jantung di aplikasi ini --
# jadi angkanya ditampilkan dengan label "perkiraan", bukan sebagai pengukuran.
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
    """Bersihkan data anggota gym, seragamkan label, lalu bubuhkan hasil klaster K-Prototypes."""
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
# K DITETAPKAN OLEH SIKU KURVA BIAYA, TITIK AWAL OLEH BIAYA YANG SAMA. Untuk
# setiap kandidat K, sekumpulan titik awal diadu dan yang biayanya paling rendah
# yang dipakai; barisan biaya-terbaik-per-K itulah kurva yang dicari sikunya.
# Kedua keputusan memakai satu ukuran -- fungsi biaya yang memang diminimalkan
# algoritmanya -- sehingga menambah percobaan titik awal hanya bisa menurunkan
# kurva, tidak pernah merusaknya.
#
# Metrik mutu tidak ikut campur di sini. Calinski-Harabasz, Silhouette-Gower,
# dan Rasio Hamming dihitung SESUDAH K ditetapkan, di fungsi *_performance.
def elbow_distances(k_values, costs) -> np.ndarray:
    """Jarak tiap titik kurva biaya ke garis lurus yang menghubungkan kedua ujungnya.

    Inilah cara Metode Siku dihitung tanpa menaksir grafik dengan mata. Kedua
    sumbu dinormalkan ke 0..1 lebih dulu supaya hasilnya tidak bergantung pada
    satuan biaya (WCSS puluhan, Hamming Cost ribuan). Titik yang paling jauh
    dari garis lurus itu adalah tikungan paling tajam -- di situlah tambahan
    satu klaster berhenti memberi penurunan biaya yang sepadan.
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
    numeric_columns = ["Age", "Weight (kg)", "Height (m)", "BMI"]
    categorical_columns = ["Gender", "Activity_Level", "Experience_Label", "Fitness_Goal"]
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
    # Kategori ikut masuk ke teks CBF supaya kata kunci kategori yang dipilih
    # user ("ayam", "ikan") punya bobot di ruang TF-IDF, bukan cuma dipakai
    # sebagai filter di luar model.
    foods["CBF_Text"] = (
        foods["name"].fillna("")
        + " calories "
        + foods["calories"].round().astype(str)
        + " protein "
        + foods["proteins"].round().astype(str)
        + " fat "
        + foods["fat"].round().astype(str)
        + " carbohydrate "
        + foods["carbohydrate"].round().astype(str)
        + " cluster "
        + foods["Food_Cluster"]
        + " kategori "
        + foods["Food_Category"].str.lower()
    )
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(foods["CBF_Text"])
    foods.attrs["food_tfidf_model"] = {"vectorizer": vectorizer, "tfidf_matrix": tfidf_matrix}
    return foods


def _lowercase_names(foods: pd.DataFrame) -> pd.Series:
    """Nama menu dalam huruf kecil tanpa spasi berlebih, untuk pencocokan pola."""
    return foods["name"].fillna("").astype(str).str.lower().str.strip()


def snack_eligibility(foods: pd.DataFrame) -> pd.Series:
    """True untuk item yang pantas disajikan di slot camilan.

    Penilaiannya berdasarkan BENTUK SAJIAN, bukan jumlah kalorinya. Sepiring
    nasi tetap makanan berat walaupun porsinya dipotong jadi 80 gram, jadi
    membatasi slot camilan lewat klaster kalori saja tidak cukup.
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

    Nilainya dibulatkan ke bilangan bulat dengan metode sisa terbesar sehingga
    penjumlahan keempat slot PERSIS sama dengan target kalori harian. Membulatkan
    tiap slot sendiri-sendiri membuat totalnya meleset 1-2 kkal (mis. target
    2.322 kkal menghasilkan 2.321), dan selisih itu langsung terlihat di kartu
    Target Kalori Harian yang membandingkan konsumsi dengan targetnya.
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

    Dua pemeriksaan:

    1. Jumlah protein + lemak + karbohidrat tidak boleh melebihi 100 g per
       100 g bahan -- massanya tidak bisa lebih besar dari bahannya sendiri.
    2. Energi tercatat harus mendekati hasil hitung faktor Atwater
       (4-9-4 kkal/g). Selisih besar berarti salah satu angkanya keliru.

    Barisnya dibuang, bukan diperbaiki: menebak mana yang benar antara energi
    dan makro sama saja mengarang data.
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
    """Buang entri yang bukan hidangan siap santap (bahan mentah, non-pangan, gizi tidak masuk akal)."""
    names = foods["name"].fillna("").astype(str).str.lower().str.strip()
    is_not_human_food = names.str.contains(NOT_HUMAN_FOOD_PATTERN, regex=True, na=False)
    is_ingredient = names.str.contains(INGREDIENT_PATTERN, regex=True, na=False)
    is_fruit_ingredient = names.str.contains(FRUIT_AS_INGREDIENT_PATTERN, regex=True, na=False)
    is_excluded = names.str.contains(EXCLUDED_FOOD_PATTERN, regex=True, na=False)
    is_protected = names.str.contains(PROTECTED_OR_HARAM_DISH_PATTERN, regex=True, na=False)
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
        & ~is_not_a_meal
        & nutrition_is_plausible(foods)
    )

    # Ketersediaan gambar TIDAK lagi menentukan apakah sebuah menu boleh
    # direkomendasikan. Dulu menu yang gambarnya tidak bisa dimuat langsung
    # dibuang, dan itu menimbulkan tiga masalah sekaligus:
    #
    #   1. Menu hilang karena alasan yang tidak ada hubungannya dengan gizi.
    #      Tautan CDN pihak ketiga lapuk; 63 dari 260 menu sudah kehilangan
    #      gambarnya, dan angka itu terus bertambah.
    #   2. Jumlah menu jadi tidak bisa direproduksi. Pemeriksaannya lewat
    #      jaringan, jadi hasilnya bergantung pada koneksi dan pembatasan laju
    #      host saat itu -- laporan penelitian bisa menyebut angka berbeda tiap
    #      kali dijalankan.
    #   3. Pemuatan pertama di mesin baru makan ~33 detik hanya untuk memeriksa
    #      260 URL, dan berkas cache-nya tidak ikut dibawa saat repositori
    #      dipindah.
    #
    # Sekarang menu tanpa gambar tetap direkomendasikan dan kartunya memakai
    # gambar pengganti. Status gambar dibaca dari CACHE saja -- tanpa satu pun
    # permintaan jaringan saat start.
    candidates = foods[passes_name_filter].copy()
    images = candidates["image"].fillna("").astype(str)
    candidates["Has_Image"] = pd.Series(
        image_status_from_cache(images.tolist()), index=images.index, dtype=bool
    )
    return candidates


def image_status_from_cache(urls: list[str]) -> list[bool]:
    """Status gambar dari cache di disk. TIDAK menyentuh jaringan.

    URL yang belum pernah diperiksa dianggap bisa ditampilkan (optimistis):
    lebih baik mencoba memuat gambar yang ternyata mati -- kartunya toh sudah
    punya latar pengganti -- daripada menahan start-up demi memastikannya.
    Pemeriksaan sungguhan dilakukan di luar aplikasi oleh
    schema_data/repair_food_images.py, yang sekaligus mengganti tautan mati.
    """
    if not urls:
        return []
    cached = _load_image_cache()
    return [
        bool(url) and url.startswith(("http://", "https://")) and cached.get(url, True)
        for url in urls
    ]


def check_image_urls_concurrently(urls: list[str], max_workers: int = IMAGE_CHECK_MAX_WORKERS) -> list[bool]:
    """Run image_url_is_displayable over many URLs in parallel.

    Uses a thread pool because the work is network I/O bound (HEAD/GET
    requests), so threads give a near-linear speedup despite the GIL.
    executor.map preserves input order, so the result list lines up
    with `urls` exactly like the old sequential `.map()` call did.
    """
    if not urls:
        return []

    # lru_cache di image_url_is_displayable cuma hidup selama proses, jadi tiap
    # `streamlit run` diulang dari nol -- ratusan request HTTP lagi, dan itulah
    # yang bikin tampilan pertama lama. Hasilnya disimpan ke disk supaya restart
    # berikutnya nyaris instan. Cache ini murni optimasi: kalau filenya hilang,
    # rusak, atau kedaluwarsa, hasilnya tetap benar -- cuma balik lambat lagi.
    cached = _load_image_cache()
    pending = [url for url in dict.fromkeys(urls) if url not in cached]
    if pending:
        workers = max(1, min(max_workers, len(pending)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            cached.update(zip(pending, executor.map(image_url_is_displayable, pending)))
        # URL yang tadi kena pembatasan laju TIDAK ikut disimpan: jawabannya
        # cuma dugaan optimistis, dan menuliskannya ke cache akan mengunci
        # dugaan itu selama masa berlaku cache (7 hari). Dibiarkan kosong
        # supaya diperiksa ulang -- saat itu host biasanya sudah tidak sibuk.
        layak_disimpan = {url: ok for url, ok in cached.items() if url not in _THROTTLED_URLS}
        _save_image_cache(layak_disimpan)
    return [cached[url] for url in urls]


IMAGE_CACHE_PATH = DATA_DIR / ".image_check_cache.json"

# 90 hari, bukan 7. Cache ini tidak lagi menjadi gerbang yang menentukan menu
# mana yang boleh muncul -- ia hanya menentukan kartu mana yang langsung memakai
# gambar pengganti. Masa berlaku pendek dulu masuk akal saat salah tebak berarti
# menu hilang; sekarang salah tebak paling banter menampilkan gambar pengganti
# pada menu yang sebetulnya punya gambar, dan itu diperbaiki saat
# repair_food_images.py dijalankan.
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
            # Pembatasan laju TIDAK berarti gambarnya mati. Memeriksa 260 URL
            # sekaligus dengan 20 worker membuat host seperti
            # upload.wikimedia.org membalas 429, dan menganggapnya "mati" berarti
            # menu yang gambarnya baik-baik saja terbuang -- berbeda-beda tiap
            # eksekusi, sehingga jumlah menu pada laporan penelitian ikut
            # berubah tanpa datanya berubah. Diperlakukan optimistis: server
            # terbukti hidup, jadi menunya dipertahankan.
            _THROTTLED_URLS.add(url)
            return True
        return False
    except (OSError, HTTPException, ValueError):
        # OSError sudah mencakup URLError, TimeoutError, DAN ssl.SSLError.
        # Yang terakhir ini penting: ssl.SSLWantReadError sempat lolos dari
        # daftar lama (dia bukan turunan URLError) dan menjatuhkan seluruh
        # app saat cold load. Gambar yang gagal dicek cukup dianggap tidak
        # bisa ditampilkan -- jangan sampai satu URL bermasalah bikin crash.
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


def assign_food_clusters(foods: pd.DataFrame) -> pd.Series:
    """Klasterkan menu dengan K-Means lalu beri label A (karbo), B (protein), C (rendah kalori)."""
    features = foods[["calories", "proteins", "fat", "carbohydrate"]]
    scaled = MinMaxScaler().fit_transform(features)
    labels = KMeans(n_clusters=FOOD_CLUSTER_COUNT, random_state=42, n_init=10).fit_predict(scaled)
    clustered = foods.assign(_cluster=labels)
    summaries = clustered.groupby("_cluster")[["calories", "proteins", "fat", "carbohydrate"]].mean()

    low_cal_cluster = summaries["calories"].idxmin()
    remaining_for_carb = [cluster for cluster in summaries.index if cluster != low_cal_cluster]
    carb_cluster = summaries.loc[remaining_for_carb, "carbohydrate"].idxmax() if remaining_for_carb else low_cal_cluster
    remaining = [cluster for cluster in summaries.index if cluster not in {carb_cluster, low_cal_cluster}]
    protein_cluster = summaries.loc[remaining, "proteins"].idxmax() if remaining else carb_cluster

    cluster_map = {
        carb_cluster: "A",
        protein_cluster: "B",
        low_cal_cluster: "C",
    }
    return pd.Series(labels).map(cluster_map).fillna("B")


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
    exercises["CBF_Text"] = (
        exercises["Title"]
        + " "
        + exercises["Desc"]
        + " "
        + exercises["Type"]
        + " "
        + exercises["BodyPart"]
        + " "
        + exercises["Equipment"]
        + " "
        + exercises["Level"]
        + " cluster "
        + exercises["Exercise_Cluster"].astype(str)
    )
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

    # Jarak dihitung dengan FUNGSI YANG SAMA yang membentuk klasternya
    # (kprototypes_distances), bukan rumus tersendiri. Sebelumnya di sini
    # dipakai norma L2 yang tidak dikuadratkan ditambah proporsi ketidakcocokan
    # kategorikal (bobot 1/4), sedangkan pelatihan memakai jarak kuadrat
    # ditambah jumlah ketidakcocokan (bobot 1). Dua rumus berbeda atas modus
    # yang sama berarti pengguna baru bisa mendarat di klaster yang BUKAN
    # klaster terdekat menurut model -- dan bobot yang lebih kecil membuat
    # kesamaan kategorikal (jenis kelamin, tujuan, level) nyaris tidak
    # berpengaruh. Memanggil ulang fungsinya membuat keduanya tidak bisa
    # berbeda lagi di kemudian hari.
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

    Tanpa `random_state`, titik awalnya DETERMINISTIK (disebar merata lewat
    np.linspace) -- itulah yang dipakai aplikasi, supaya klaster yang sama
    selalu dihasilkan dari data yang sama tanpa perlu menyimpan seed.

    Dengan `random_state`, titik awalnya diundi. Itu hanya dipakai notebook
    pengujian untuk mengukur seberapa peka hasilnya terhadap inisialisasi:
    algoritma yang bagus tapi hasilnya berubah-ubah tiap dijalankan tidak layak
    dilaporkan sebagai temuan penelitian.
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

    Dipakai langsung oleh uji stabilitas di notebook (lewat `random_state`).
    Pemilihan titik awal terbaik dilakukan di `fit_member_cluster_model`, bukan
    di sini, supaya fungsi ini tetap punya satu tugas saja.
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


def kprototypes_distances(
    numeric: np.ndarray,
    categorical: np.ndarray,
    numeric_modes: np.ndarray,
    categorical_modes: np.ndarray,
) -> np.ndarray:
    """Matriks jarak K-Prototypes tiap baris ke tiap modus: kuadrat Euclid + jumlah ketidakcocokan kategori."""
    numeric_distance = ((numeric[:, None, :] - numeric_modes[None, :, :]) ** 2).sum(axis=2)
    categorical_distance = (categorical[:, None, :] != categorical_modes[None, :, :]).sum(axis=2)
    return numeric_distance + categorical_distance


def categorical_attribute_weights(values: np.ndarray) -> np.ndarray:
    """Bobot penyeimbang antar-atribut untuk jarak Hamming.

    MASALAHNYA. Hamming memberi tiap atribut nilai 0 atau 1, yang terlihat adil
    tetapi tidak. Sebuah atribut yang isinya nyaris seragam hampir selalu
    bernilai 0, jadi praktis tidak pernah ikut membedakan dua baris. Pada data
    latihan, `Type` 90% berisi "Strength" dan `Level` 92% berisi "Intermediate",
    sehingga peluang keduanya menyumbang jarak hanya 0,18 dan 0,16 -- sedangkan
    `BodyPart` (16 kategori) dan `Equipment` (12 kategori) menyumbang di atas
    0,83. Efeknya klaster terbentuk hanya dari dua atribut, dua lainnya menumpang.

    OBATNYA. Tiap atribut diberi bobot berbanding terbalik dengan peluangnya
    berbeda, sehingga keempatnya menyumbang setara. Diukur dengan Rasio Hamming
    polos (tanpa bobot, supaya penggarisnya tidak ikut berubah), pemisahan
    membaik dari 0,5698 menjadi 0,5230; kemurnian `Level` di dalam klaster naik
    dari 93,8% ke 99,1%.
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

    `weights` default-nya bobot penyeimbang dari data itu sendiri. Berikan
    array satuan untuk mendapatkan Hamming polos (dipakai notebook saat
    membandingkan kondisi sebelum dan sesudah pembobotan).
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

    Inilah fungsi biaya (cost function) K-Modes -- yang diminimalkan saat
    melatih, dan yang kurvanya dicari sikunya saat menetapkan K. Tanpa `weights`
    hasilnya Hamming Cost POLOS (tiap atribut bernilai 0/1), yaitu angka yang
    dilaporkan di tabel hasil; dengan bobot penyeimbang hasilnya adalah biaya
    yang benar-benar dioptimalkan `fit_kmodes`.
    """
    mismatch = (values[:, None, :] != modes[None, :, :]).astype(float)
    if weights is not None:
        distances = mismatch @ weights
    else:
        distances = mismatch.sum(axis=2)
    return float(distances[np.arange(len(labels)), labels].sum())


def hamming_separation_ratio(distances: np.ndarray, labels: np.ndarray) -> float:
    """Rata-rata jarak Hamming DALAM klaster dibagi rata-rata ANTAR klaster.

    `distances` adalah matriks jarak yang sudah dihitung sebelumnya. Matriks itu
    tidak bergantung pada label, jadi cukup dihitung sekali lalu dipakai ulang
    untuk menilai semua kandidat -- itulah yang membuat pencarian K sekaligus
    pencarian titik awal tetap murah.

    Makin kecil makin baik: anggota satu klaster jauh lebih mirip satu sama lain
    daripada dengan anggota klaster lain.
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
    numeric_columns = ["Age", "Weight (kg)", "Height (m)", "BMI"]
    categorical_columns = ["Gender", "Activity_Level", "Experience_Label", "Fitness_Goal"]
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
    """Ukur performa K-Means: inertia, Calinski-Harabasz, Silhouette, dan sebaran klaster.

    DUA METRIK MUTU, KEDUANYA PENILAI. Inertia hanya bisa turun saat K bertambah,
    jadi ia tidak bisa menilai apa pun; ia dilaporkan sebagai keterangan kerapatan.
    Yang menilai adalah dua metrik yang saling melengkapi:

      Calinski-Harabasz -- sebaran ANTAR klaster dibagi sebaran DI DALAM klaster.
                           Melihat seluruh struktur sekaligus, tanpa batas atas.
      Silhouette        -- dihitung per titik: seberapa dekat sebuah menu ke
                           klasternya sendiri dibanding klaster tetangganya.
                           Terbatas -1..1, jadi bisa dibandingkan lintas dataset.

    Keduanya dihitung SESUDAH K ditetapkan. K-Means makanan memakai K struktural
    (FOOD_CLUSTER_COUNT), jadi tidak ada satu pun angka di sini yang ikut memilih K.
    """
    features = foods[["calories", "proteins", "fat", "carbohydrate"]]
    scaled = MinMaxScaler().fit_transform(features)
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
    """Matriks Gower Distance antar seluruh pasangan baris data campuran.

    Gower menyatukan dua tipe data dalam satu skala 0..1:

        atribut numerik     -> |x_i - x_j| / rentang atribut itu
        atribut kategorikal -> 0 bila sama, 1 bila berbeda

    lalu seluruh suku dirata-ratakan. Karena tiap suku sudah dibagi rentangnya
    sendiri, hasilnya TIDAK berubah oleh penskalaan: kolom mentah dan kolom
    hasil MinMaxScaler menghasilkan matriks yang sama.
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
    """Silhouette Score data campuran, dihitung di atas matriks Gower yang sudah jadi.

    URUTANNYA: matriks jarak Gower seluruh data dibentuk lebih dulu, baru
    matriks itu dimasukkan ke `silhouette_score(..., metric="precomputed")`.

    Jarak pembentuk klaster (kuadrat Euclid + ketidakcocokan) TIDAK dipakai di
    sini. Skalanya tidak terbatas dan bagian numeriknya berpangkat dua,
    sehingga nilai Silhouette yang dihasilkannya tidak sebanding dengan angka
    Silhouette mana pun di literatur. Gower membatasi setiap atribut ke 0..1
    lebih dulu, jadi -1..1 pada hasilnya berarti seperti yang biasa dimaksud.
    """
    sample = _evaluation_sample_index(len(numeric))
    if sample is None:
        sample = np.arange(len(numeric))
    matriks_gower = gower_pairwise_distances(numeric[sample], categorical[sample])
    return safe_silhouette(matriks_gower, np.asarray(labels)[sample], metric="precomputed")


def kprototypes_pairwise_distances(numeric: np.ndarray, categorical: np.ndarray) -> np.ndarray:
    """Matriks jarak K-Prototypes antar seluruh pasangan baris, untuk silhouette precomputed."""
    numeric_distance = ((numeric[:, None, :] - numeric[None, :, :]) ** 2).sum(axis=2)
    categorical_distance = (categorical[:, None, :] != categorical[None, :, :]).sum(axis=2)
    return numeric_distance + categorical_distance


def categorical_pairwise_distances(values: np.ndarray) -> np.ndarray:
    """Matriks jarak Hamming antar seluruh pasangan baris kategorikal."""
    return (values[:, None, :] != values[None, :, :]).sum(axis=2).astype(float)


def _food_tfidf_model(foods: pd.DataFrame) -> tuple[TfidfVectorizer, np.ndarray]:
    """Pasangan (vectorizer, tfidf_matrix) yang sudah terlatih untuk `foods`.

    Memakai ulang model yang sudah dihitung di prepare_foods() dan dititipkan
    pada foods.attrs["food_tfidf_model"] -- pola .attrs yang sama dengan
    member_cluster_model -- supaya recommend_foods() tidak melatih ulang TF-IDF
    di setiap pemanggilan. Kalau attrs-nya tidak ada atau sudah tidak cocok
    (mis. dioper DataFrame makanan berukuran lain), modelnya dilatih ulang di
    sini, jadi hasilnya tetap benar dalam kedua keadaan.
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

    Slot camilan disaring KERAS di sini dan tidak pernah dilonggarkan pada
    fallback mana pun: lebih baik slotnya kosong daripada menawarkan nasi atau
    mie sebagai camilan.
    """
    if meal_slot == SNACK_SLOT and "Is_Snack" in foods.columns:
        return foods[foods["Is_Snack"].fillna(False).astype(bool)]
    if meal_slot == BREAKFAST_SLOT and "name" in foods.columns:
        names = foods["name"].fillna("").astype(str).str.lower().str.strip()
        return foods[~names.str.contains(BREAKFAST_UNSUITABLE_PATTERN, regex=True, na=False)]
    return foods


def is_staple_food(foods: pd.DataFrame) -> pd.Series:
    """True untuk makanan pokok sumber karbohidrat utama."""
    names = foods["name"].fillna("").astype(str).str.lower().str.strip()
    return names.str.contains(STAPLE_PATTERN, regex=True, na=False)


def _rank_foods(
    foods: pd.DataFrame,
    preference: str,
    categories: Iterable[str] | None,
    *,
    vectorizer: TfidfVectorizer | None = None,
    tfidf=None,
) -> pd.DataFrame:
    """Urutkan makanan: kecocokan kategori dulu, lalu skor cosine similarity CBF."""
    if vectorizer is None or tfidf is None:
        vectorizer = TfidfVectorizer(stop_words="english")
        tfidf = vectorizer.fit_transform(foods["CBF_Text"])
    query = build_preference_query(preference, categories)
    scores = cosine_similarity(vectorizer.transform([query]), tfidf).ravel()
    ranked = foods.assign(
        _score=scores,
        _category=match_food_categories(foods, categories),
        _match=match_food_keywords(foods, parse_preference_keywords(preference)),
    )
    return ranked.sort_values(["_category", "_match", "_score"], ascending=[False, False, False])


def _candidate_tiers(
    pool: pd.DataFrame,
    cluster: str | None,
    *,
    cluster_first: bool = False,
) -> list[pd.DataFrame]:
    """Urutan pelonggaran filter saat slot sulit diisi.

    Kategori dan klaster boleh dilonggarkan (kalau tidak, satu kategori sempit
    membuat slot kosong); kelayakan camilan tidak, karena `pool` sudah disaring
    lebih dulu oleh slot_candidate_pool().

    `cluster_first` dipakai oleh swap: Dynamic Portion Constraint mensyaratkan
    pengganti berasal dari klaster yang sama, jadi di sana klaster dipertahankan
    lebih lama daripada kategori. Saat menyusun menu baru urutannya dibalik --
    kategori adalah pilihan eksplisit user, klaster hanya alat internal.
    """
    in_category = pool["_category"].astype(bool)
    in_cluster = pool["Food_Cluster"] == cluster if cluster else pd.Series(True, index=pool.index)
    middle = [pool[in_cluster], pool[in_category]] if cluster_first else [pool[in_category], pool[in_cluster]]
    return [pool[in_cluster & in_category], *middle, pool]


def split_slot_quota(slot_quota: float, item_count: int) -> list[int]:
    """Bagi kuota kalori satu slot menjadi target per item dalam bilangan bulat.

    Sisa pembagian dibagikan ke item-item pertama (metode sisa terbesar), supaya
    penjumlahan target seluruh item PERSIS sama dengan kuota slot. Pembulatan
    per item tanpa koreksi ini membuat total harian meleset beberapa kkal dari
    kebutuhan energi pengguna -- kecil, tapi merusak klaim bahwa totalnya setara.
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
) -> dict[str, list[dict]]:
    """Susun menu harian empat slot yang totalnya persis sama dengan target kalori.

    Kuota tiap slot = target kalori harian x proporsi slot (MEAL_DISTRIBUTION),
    lalu dibagi rata ke item-item di slot itu. Gramasi tiap item dihitung dengan
    Persamaan Konversi Kalori ke Gramasi dan divalidasi Volumetric Sanity Check;
    item yang gagal didiskualifikasi dan sistem lanjut ke peringkat CBF berikutnya.
    """
    excluded = set(excluded_food_ids or [])
    vectorizer, tfidf = _food_tfidf_model(foods)
    ranked = _rank_foods(foods, preference, categories, vectorizer=vectorizer, tfidf=tfidf)

    quotas = slot_calorie_quota(nutrition.target_calories)
    recommendations: dict[str, list[dict]] = {}
    used_ids = set(excluded)

    for meal_slot, clusters in MEAL_TEMPLATE.items():
        slot_quota = quotas[meal_slot]
        item_targets = split_slot_quota(slot_quota, len(clusters))
        slot_pool = slot_candidate_pool(ranked, meal_slot)
        recommendations[meal_slot] = []

        staple_taken = False
        for cluster, item_target in zip(clusters, item_targets):
            available = slot_pool[~slot_pool["id"].isin(used_ids)]

            # Satu makanan pokok saja per slot. Kandidat non-pokok dicoba lebih
            # dulu; kalau benar-benar tidak ada yang lolos Volumetric Sanity
            # Check, barulah seluruh kandidat dipakai lagi -- lebih baik satu
            # slot berisi dua sumber karbohidrat daripada kuota kalorinya hilang
            # dan total harian tidak lagi sama dengan kebutuhan energi pengguna.
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
        for helper in ("_score", "_category", "_match"):
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
) -> dict | None:
    """Ganti satu item dengan Dynamic Portion Constraint.

    Pengganti diambil dari KLASTER YANG SAMA dengan item yang diganti, lalu
    gramasinya DIHITUNG ULANG dengan Persamaan Konversi Kalori ke Gramasi
    terhadap kuota kalori item tersebut -- bukan dipakai pada gramasi default
    si pengganti, karena itu akan merusak total kalori harian yang sudah
    dikalkulasi dari kebutuhan energi pengguna.
    """
    excluded = {int(food_id) for food_id in (excluded_food_ids or [])}
    excluded.add(int(current_food["id"]))

    slot = meal_slot or current_food.get("meal_slot")
    pool = slot_candidate_pool(foods, slot)
    pool = pool[~pool["id"].isin(excluded)]
    if pool.empty:
        return None

    ranked = _rank_foods(pool, preference, categories)
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


def recommend_exercises(
    exercises: pd.DataFrame,
    *,
    body_part: str,
    workout_type: str,
    equipment_preference: str,
    experience_level: str,
    fitness_goal: str,
    limit: int = 5,
) -> pd.DataFrame:
    """Susun daftar latihan teratas: saring per level dan target otot, ranking TF-IDF, lalu ragamkan alat."""
    allowed_levels = LEVEL_ALLOWLIST[experience_level]
    filtered = exercises[exercises["Level"].isin(allowed_levels)].copy()
    target_parts = resolve_target_body_parts(body_part)
    if target_parts is not None:
        filtered = filtered[filtered["BodyPart"].isin(target_parts)]
    target_filtered = filtered.copy()
    if workout_type != "Any":
        filtered = filtered[filtered["Type"] == workout_type]
    if filtered.empty and workout_type != "Any":
        filtered = target_filtered
    if filtered.empty:
        selected = filtered.copy()
        params = TRAINING_PARAMETERS[(normalize_goal(fitness_goal), experience_level)]
        for key, value in params.items():
            selected[key] = value
        selected["Similarity"] = pd.Series(dtype=float)
        return selected

    query = f"{body_part} {workout_type} {equipment_preference} {experience_level}"
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf = vectorizer.fit_transform(filtered["CBF_Text"])
    scores = cosine_similarity(vectorizer.transform([query]), tfidf).ravel()
    ranked = filtered.assign(Similarity=scores).sort_values("Similarity", ascending=False)

    selected = _enforce_equipment_diversity(ranked, limit)
    params = TRAINING_PARAMETERS[(normalize_goal(fitness_goal), experience_level)]
    for key, value in params.items():
        selected[key] = value
    selected["Similarity"] = selected["Similarity"].round(3)
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
    """Cari satu latihan pengganti yang paling mirip, di luar yang sedang tampil dan yang sudah ditolak."""
    experience_level = filters.get("experience_level", "Beginner")
    fitness_goal = filters.get("fitness_goal", "Maintain Weight")
    body_part = filters.get("body_part", "Any")
    workout_type = filters.get("workout_type", "Any")
    equipment_preference = filters.get("equipment_preference", "Any")

    allowed_levels = LEVEL_ALLOWLIST[experience_level]
    candidates = exercises[exercises["Level"].isin(allowed_levels)].copy()
    target_parts = resolve_target_body_parts(body_part)
    if target_parts is not None:
        candidates = candidates[candidates["BodyPart"].isin(target_parts)]
    target_candidates = candidates.copy()
    if workout_type != "Any":
        candidates = candidates[candidates["Type"] == workout_type]
    if candidates.empty and workout_type != "Any":
        candidates = target_candidates

    current_title = str(current_exercise.get("Title", ""))
    selected_titles = {
        str(title)
        for title in current_recommendations.get("Title", pd.Series(dtype=str)).tolist()
    }
    excluded_titles = {str(title) for title in filters.get("excluded_titles", [])}
    candidates = candidates[~candidates["Title"].astype(str).isin(selected_titles | excluded_titles | {current_title})]
    if candidates.empty:
        return None

    query = f"{body_part} {workout_type} {equipment_preference} {experience_level}"
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf = vectorizer.fit_transform(candidates["CBF_Text"])
    scores = cosine_similarity(vectorizer.transform([query]), tfidf).ravel()
    ranked = candidates.assign(Similarity=scores)
    if equipment_preference != "Any":
        ranked["_equipment_match"] = (ranked["Equipment"] == equipment_preference).astype(int)
        ranked = ranked.sort_values(["_equipment_match", "Similarity"], ascending=False)
    else:
        ranked = ranked.sort_values("Similarity", ascending=False)

    replacement = ranked.iloc[0].drop(labels=["_equipment_match"], errors="ignore").to_dict()
    params = TRAINING_PARAMETERS[(normalize_goal(fitness_goal), experience_level)]
    replacement.update(params)
    replacement["Similarity"] = round(float(replacement.get("Similarity", 0)), 3)
    return replacement


def _enforce_equipment_diversity(ranked: pd.DataFrame, limit: int) -> pd.DataFrame:
    """Ambil tiga peringkat teratas dengan alat berbeda dulu, sisanya menyusul urut skor."""
    selected_indices = []
    used_equipment = set()

    for index, row in ranked.iterrows():
        if row["Equipment"] in used_equipment:
            continue
        selected_indices.append(index)
        used_equipment.add(row["Equipment"])
        if len(selected_indices) >= min(limit, 3):
            break

    for index in ranked.index:
        if len(selected_indices) >= limit:
            break
        if index not in selected_indices:
            selected_indices.append(index)

    return ranked.loc[selected_indices].copy()


def profile_payload(nutrition: NutritionResult, **profile) -> dict:
    """Gabungkan data profil dan hasil perhitungan gizi jadi satu dict siap disimpan."""
    payload = dict(profile)
    payload.update(asdict(nutrition))
    return payload
