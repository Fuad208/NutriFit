"""Uji regresi saringan menu: kata "segar" dan sinkronisasi CSV vs basis data.

LATAR MASALAHNYA. `INGREDIENT_PATTERN` memuat `\\bsegar\\b` sebagai penanda bahan
mentah. Pada dataset TKPI, kata itu punya DUA arti yang berlawanan:

    "Sapi daging gemuk segar", "Udang galah segar", "Daun katuk segar"
        -> bahan mentah, harus dimasak, tidak boleh direkomendasikan.
    "Mangga segar", "Pisang kepok segar", "Apel malang segar"
        -> justru bentuk siap santapnya, dan camilan tersehat yang bisa
           ditawarkan aplikasi gizi.

Menyamaratakan keduanya membuang 52 buah segar diam-diam. Tidak ada galat yang
muncul; jumlah menu hanya berkurang tanpa alasan yang terlihat.

Cacat ini sempat tak terdeteksi karena pengujian memakai `data/food_nutrition.csv`
yang memuat nama sudah dipendekkan ("Mangga"), sedangkan tabel database yang
benar-benar dibaca aplikasi menyimpan nama asli TKPI ("Mangga segar"). Karena itu
berkas ini juga menguji bahwa kedua sumber tetap sinkron.
"""
import sys
import warnings
from pathlib import Path

ROOT = Path(r"c:\Kuliah\Semester 8\Tugas Akhir\Coding\NutriFit")
sys.path.insert(0, str(ROOT))

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import src.recommender as R  # noqa: E402


def contoh(nama: str) -> pd.DataFrame:
    """Satu baris bergizi wajar, supaya yang diuji murni saringan namanya."""
    return pd.DataFrame({
        "id": [1], "name": [nama], "calories": [60],
        "proteins": [1.0], "fat": [0.5], "carbohydrate": [13.0], "image": [""],
    })


def diterima(nama: str) -> bool:
    """True bila satu nama menu lolos penyaringan menu yang layak direkomendasikan."""
    return len(R.filter_recommendable_foods(contoh(nama))) == 1


print("== buah segar HARUS diterima ==")
BUAH = [
    "Mangga segar", "Mangga benggala segar", "Apel malang segar", "Melon segar",
    "Alpukat segar", "Anggur hutan segar", "Salak pondoh segar", "Sawo Manila segar",
    "Rambutan binjai segar", "Nanas palembang segar", "Markisa segar", "Kedondong segar",
    "Buah Naga Merah segar", "Jeruk banjar segar", "Pisang kepok segar",
    "Pisang angleng (pisang ampyang) segar", "Lemon segar", "Matoa segar",
    "Lontar segar", "Kawista segar", "Terung belanda segar", "Sukun tua segar",
]
for nama in BUAH:
    assert diterima(nama), f"buah segar terbuang: {nama}"
print(f"   {len(BUAH)} buah segar lolos saringan")

print("\n== bahan mentah HARUS tetap ditolak walau namanya memuat 'segar' ==")
MENTAH = [
    "Sapi daging gemuk segar", "Anak sapi daging kurus segar", "Babi daging gemuk segar",
    "Udang galah segar", "Udang besar segar", "Cumi-cumi segar", "Rajungan segar",
    "Belut segar", "Ayam hati segar", "Sapi otak segar", "Sapi usus segar",
    "Telur bebek tambak segar", "Telur burung puyuh segar", "Susu skim segar",
    "Daun katuk segar", "Daun singkong segar", "Cabai merah segar", "Bayam segar",
    "Wortel Segar", "Terong segar", "Taoge segar", "Tomat merah segar",
    "Kuda daging segar", "Kelinci daging segar", "Ulat sagu segar",
]
for nama in MENTAH:
    assert not diterima(nama), f"bahan mentah bocor ke rekomendasi: {nama}"
print(f"   {len(MENTAH)} bahan mentah tetap tertolak")

print("\n== bentuk NON-buah dari tanaman buah tetap ditolak ==")
# Pengecualian buah hanya menetralkan aturan "segar"; aturan lain tetap penuh.
NON_BUAH = ["Jantung Pisang segar", "Bonggol Pisang", "Bonggol Pisang kering",
            "Tepung Pisang", "Nangka muda", "Kolang-kaling"]
for nama in NON_BUAH:
    assert not diterima(nama), f"bagian tanaman bocor: {nama}"
print(f"   {len(NON_BUAH)} bentuk non-buah tetap tertolak")

print("\n== pengecualian tidak melemahkan saringan lain ==")
TETAP_HARAM = ["Babi panggang", "Daging anjing", "Sate kura-kura", "Tempe bongkrek",
               "Gadung rebus", "Bir hitam", "Bungkil kelapa"]
for nama in TETAP_HARAM:
    assert not diterima(nama), f"saringan keamanan/halal jebol: {nama}"
print(f"   {len(TETAP_HARAM)} menu terlarang tetap tertolak")

print("\n== hidangan biasa tidak ikut terdampak ==")
BIASA = ["Nasi goreng", "Soto ayam", "Rendang daging", "Gado-gado", "Bakwan jagung"]
for nama in BIASA:
    assert diterima(nama), f"hidangan biasa ikut terbuang: {nama}"
print(f"   {len(BIASA)} hidangan biasa tetap lolos")

print("\n== biji, bukan buah, tetap ditolak walau namanya memuat nama buah ==")
# "Kacang mete/biji jambu monyet" sempat lolos lewat kata "jambu" pada
# FRESH_FRUIT_PATTERN, padahal yang dimaksud bijinya -- bahan, bukan buah.
BIJI = ["Kacang mete/biji jambu monyet segar", "Kacang mete", "Kacang mede segar",
        "Biji nangka", "Nangka biji"]
for nama in BIJI:
    assert not diterima(nama), f"biji lolos sebagai buah: {nama}"
print(f"   {len(BIJI)} nama berupa biji tetap tertolak")

print("\n== buah segar harus LAYAK mengisi slot camilan ==")
# Lolos saringan saja tidak cukup: kalau Is_Snack False, buahnya tidak akan
# pernah muncul di slot camilan dan penambahannya tidak terasa oleh pengguna.
BUAH_CAMILAN = ["Mangga segar", "Pisang kepok segar", "Melon segar", "Matoa segar",
                "Kawista segar", "Lontar segar", "Lemon segar", "Terung belanda segar",
                "Buah rukam segar", "Carica papaya segar", "Biwah segar", "Kranji segar"]
for nama in BUAH_CAMILAN:
    layak = bool(R.snack_eligibility(contoh(nama)).iloc[0])
    assert layak, f"buah tidak diakui sebagai camilan: {nama}"
print(f"   {len(BUAH_CAMILAN)} buah diakui layak jadi camilan")

print("\n== makanan berat tetap TIDAK boleh masuk slot camilan ==")
BUKAN_CAMILAN = ["Nasi goreng", "Mie ayam", "Soto ayam", "Rendang daging",
                 "Bubur ayam", "Gudeg", "Sayur lodeh", "Bakso"]
for nama in BUKAN_CAMILAN:
    layak = bool(R.snack_eligibility(contoh(nama)).iloc[0])
    assert not layak, f"makanan berat bocor ke slot camilan: {nama}"
print(f"   {len(BUKAN_CAMILAN)} makanan berat tetap tertolak dari slot camilan")

print("\n== hasil penyisiran kelayakan: 14 temuan yang lolos pembantahan ==")
# 12 peninjau menyisir seluruh 866 nama, menghasilkan 65 tuduhan. Setiap tuduhan
# diadu dengan pembantah adversarial; 51 gugur, 14 bertahan.
TIDAK_LAYAK = [
    "Es Sirup", "Lemonade", "Lemon Squasih", "Markisa squash", "Markisa squash BD",
    "Kopi bagian yang larut", "Melase", "Setrup sirup",
    "Jagung Kuning giling", "Jagung Putih giling",
    "Jagung Kuning pipil lama", "Jagung Putih pipil lama", "Jali", "Jawawut",
]
for nama in TIDAK_LAYAK:
    assert not diterima(nama), f"item tidak layak masih lolos: {nama}"
print(f"   {len(TIDAK_LAYAK)} temuan terkonfirmasi tetap tertolak")

print("\n== bumbu & bahan pelengkap harus tertolak ==")
# CATATAN KEPUTUSAN. Penyisiran adversarial sebelumnya MEMBANTAH sebagian nama di
# bawah dengan alasan "komponen sah hidangan Indonesia" -- dan sebagai komponen
# memang benar. Tetapi pemilik produk menilai kehadirannya di daftar rekomendasi
# tetap salah: aplikasi menyodorkan tiap baris sebagai menu yang dimakan sendiri
# dalam porsi gram, dan tidak satu pun dari ini disantap begitu. Penilaian pemilik
# produk mengalahkan hasil pembantah otomatis.
BUMBU = ["Petis Ikan", "Petis Udang", "Petis udang pasta", "Taoco",
         "Tauco cap DAS cake", "Tauji cap singa", "Prey (bawang daun)",
         "Kepala Susu (Krim)", "Asam masak di pohon",
         "Kluwek", "Peterseli", "Kucai", "Kucai Muda (Lokio)", "Wijen",
         "Kenari", "Gelatine", "Coklat bubuk"]
for nama in BUMBU:
    assert not diterima(nama), f"bumbu/bahan masih lolos: {nama}"
print(f"   {len(BUMBU)} bumbu & bahan pelengkap tertolak")

print("\n== sayur & lalapan MENTAH harus tertolak ==")
# Semuanya memang dimakan di Indonesia, tetapi sebagai lalapan pendamping nasi
# dalam beberapa lembar -- bukan hidangan yang disantap sendirian 200-400 g
# seperti yang dihitung Persamaan Konversi Kalori ke Gramasi.
LALAPAN = ["Jotang", "Krokot", "Tespong daun", "Susupan", "Tekokak", "Leunca buah",
           "Karawila", "Paria (Pare)", "Pe-Cay", "Terung panjang", "Pepaya Muda",
           "Mostarda metan -sawi", "Kool Kembang", "Kool Merah kool putih", "Bit",
           "Baligo", "Erbis", "Purundawa", "Gambas (Oyong)", "Kentang Hitam", "Andewi"]
for nama in LALAPAN:
    assert not diterima(nama), f"sayur mentah masih lolos: {nama}"
print(f"   {len(LALAPAN)} sayur/lalapan mentah tertolak")

print("\n== tapi versi MATANG-nya wajib selamat ==")
# Anchor pola lalapan sempat terlalu lebar dan ikut membuang "Paria Putih kukus"
# serta "Gambas lodeh". Uji ini yang menangkapnya.
MATANG = ["Paria Putih kukus", "Gambas lodeh", "Parede baleh masakan",
          "Terung panjang kukus", "Terong kukus", "Pepaya lodeh", "Sop Kool",
          "Sop Kool dan Wortel", "setup pepaya", "Sayur bunga pepaya",
          "Cap cai sayur", "Pelecing kangkung", "Terong Asam"]
for nama in MATANG:
    assert diterima(nama), f"hidangan matang ikut terbuang: {nama}"
print(f"   {len(MATANG)} hidangan matang tetap lolos")

print("\n== hidangan turunannya TIDAK boleh ikut terbuang ==")
# Anchor pola bumbu sengaja ketat. Kalau sampai melebar, hidangan sah ini gugur.
TURUNAN = ["Bagea kenari asin", "Bagea kenari manis", "kue bolu kenari",
           "Pindang kenari masakan", "Enting-enting wijen", "Coklat Manis batang",
           "Coklat Pahit batang", "ikan mas bumbu kuning", "Buncis asam",
           "Terong Asam", "Oncom pepes", "Bekasam",
           "tempe oreg/sayur tempe/sambal tempe", "Tumis bayam bersantan"]
for nama in TURUNAN:
    assert diterima(nama), f"hidangan sah ikut terbuang: {nama}"
print(f"   {len(TURUNAN)} hidangan turunan tetap lolos")

print("\n== yang DIBANTAH dan memang makanan harus tetap ada ==")
# "Bit" sengaja TIDAK di sini lagi: ia bit mentah, dan sudah masuk daftar sayur
# mentah di atas atas keputusan pemilik produk.
DIBANTAH = ["Kwaci", "Rumput laut", "Keong", "Oncom", "Oncom Goreng "]
for nama in DIBANTAH:
    assert diterima(nama), f"item yang sudah dibantah ikut terbuang: {nama}"
print(f"   {len(DIBANTAH)} item hasil bantahan tetap lolos")

print("\n== nama mirip yang harus SELAMAT dari pola ketat ==")
MIRIP = ["Es krim", "Es Mambo", "Es Krim (Coconut milk)", "Jagung Rebus",
         "Jagung grontol", "Nasi jagung", "Jagung muda", "Jagung titi",
         "Jagung Kuning pipil baru", "Jagung Putih pipil baru",
         "Markisa segar", "Lemon segar"]
for nama in MIRIP:
    assert diterima(nama), f"pola terlalu lebar, ikut membuang: {nama}"
print(f"   {len(MIRIP)} nama serupa tetap lolos")

print("\n== pola tidak boleh punya grup penangkap ==")
# Grup penangkap membuat pandas melempar UserWarning setiap kali saringan
# dijalankan, dan peringatan itu ikut tercetak di keluaran notebook pengujian.
import re  # noqa: E402

for nama_pola in ["NOT_HUMAN_FOOD_PATTERN", "INGREDIENT_PATTERN", "RAW_FRESH_PATTERN",
                  "FRESH_FRUIT_PATTERN", "FRUIT_PATTERN", "FRUIT_AS_INGREDIENT_PATTERN",
                  "EXCLUDED_FOOD_PATTERN", "PROTECTED_OR_HARAM_DISH_PATTERN",
                  "SNACK_FORM_PATTERN", "NOT_SNACK_PATTERN", "SNACK_ALWAYS_PATTERN"]:
    pola = getattr(R, nama_pola, None)
    if pola is None:
        continue
    jumlah = re.compile(pola).groups
    assert jumlah == 0, f"{nama_pola} punya {jumlah} grup penangkap, pakai (?:...)"
print("   seluruh pola bebas grup penangkap")

print("\n== saringan berjalan tanpa peringatan apa pun ==")
with warnings.catch_warnings():
    warnings.simplefilter("error")
    R.filter_recommendable_foods(contoh("Nasi goreng"))
    R.snack_eligibility(contoh("Mangga segar"))
print("   filter_recommendable_foods dan snack_eligibility bersih")

print("\n== CSV benih dan basis data harus sinkron ==")
# Kalau keduanya menyimpang, notebook pengujian mengukur dataset yang BUKAN
# dipakai pengguna -- tanpa satu pun galat muncul untuk memberi tahu.
try:
    db_anggota, db_makanan, db_latihan = R.load_dataset_tables()
except Exception as galat:                      # basis data tidak tersedia
    print(f"   dilewati: basis data tidak bisa dihubungi ({type(galat).__name__})")
else:
    def selisih(csv: pd.DataFrame, tabel: pd.DataFrame, kunci: str | None = None) -> int:
        """Banyaknya sel yang berbeda antara tabel CSV dan tabel database."""
        assert len(csv) == len(tabel), f"jumlah baris beda: CSV {len(csv)}, DB {len(tabel)}"
        a, b = (csv, tabel) if not kunci else (
            csv.set_index(kunci).sort_index(), tabel.set_index(kunci).sort_index())
        total = 0
        for kolom in [c for c in a.columns if c in b.columns]:
            x, y = a[kolom], b[kolom]
            if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(y):
                total += int((~np.isclose(x.fillna(-9e9), y.fillna(-9e9))).sum())
            else:
                total += int((x.fillna("").astype(str).str.strip()
                              != y.fillna("").astype(str).str.strip()).sum())
        return total

    DATA = ROOT / "data"
    for nama, berkas, tabel, kunci in [
        ("menu makanan", "food_nutrition.csv", db_makanan, "id"),
        ("program latihan", "training_program.csv", db_latihan, None),
        ("profil anggota", "gym_members.csv", db_anggota, None),
    ]:
        beda = selisih(pd.read_csv(DATA / berkas), tabel, kunci)
        assert beda == 0, (
            f"{nama}: {beda} nilai berbeda antara CSV dan basis data. "
            "Jalankan python schema_data/import_csv_to_db.py"
        )
        print(f"   {nama:16s} sinkron")

    # Kedua sumber harus menghasilkan jumlah menu yang sama persis.
    dari_db = len(R.prepare_foods(db_makanan))
    dari_csv = len(R.prepare_foods(pd.read_csv(DATA / "food_nutrition.csv")))
    assert dari_db == dari_csv, f"menu dari DB {dari_db} != dari CSV {dari_csv}"
    print(f"   kedua sumber menghasilkan {dari_db} menu")

print("\nSEMUA ASSERT SARINGAN MENU LOLOS")
