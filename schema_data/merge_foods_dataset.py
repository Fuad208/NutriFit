"""Gabungkan dataset menu tambahan (foods.csv) ke food_nutrition.csv.

ATURAN YANG DISEPAKATI:
  1. Hanya baris yang logis sebagai MENU SIAP SANTAP yang masuk. Bahan mentah,
     tepung, bumbu, minyak, gula, minuman, susu formula, MPASI pabrikan, obat,
     biskuit bermerek, jeroan, dan satwa non-halal/dilindungi dibuang.
  2. Kalau namanya BENTROK dengan dataset lama, dataset lama menang dan baris
     barunya dibuang. Alasannya: dataset lama seluruhnya dari satu sumber (TKPI),
     dan mencampur dua sumber untuk makanan yang sama membuat satu tabel memuat
     dua nilai gizi berbeda untuk hal yang sama.
  3. Baris yang nilai gizinya mustahil dibuang (lihat _validitas_fisik).

KONVERSI: energi sumber dalam kJ, dataset memakai kkal -> kkal = kJ / 4,184.

Skrip ini TIDAK mengarang nilai apa pun. Kolom `image` untuk baris baru dibiarkan
KOSONG, karena sumbernya memang tidak menyediakan gambar.

CARA PAKAI:
    python schema_data/merge_foods_dataset.py --sumber "C:/.../foods.csv"
    python schema_data/merge_foods_dataset.py --sumber "..." --tulis
    python schema_data/merge_foods_dataset.py --sumber "..." --tulis --db
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.recommender import EXCLUDED_FOOD_PATTERN  # noqa: E402

CSV_TUJUAN = ROOT_DIR / "data" / "food_nutrition.csv"
LAPORAN = ROOT_DIR / "data" / "penggabungan_menu.csv"
DIBUANG = ROOT_DIR / "data" / "penggabungan_dibuang.csv"

KJ_PER_KKAL = 4.184

# Batas toleransi selisih antara energi tercatat dan energi hasil hitung makro
# memakai faktor Atwater (protein 4, lemak 9, karbohidrat 4 kkal/g).
TOLERANSI_ENERGI = 0.25

# Pola nama yang JELAS bukan menu siap santap. Diurutkan supaya laporan
# menyebutkan alasan pembuangan yang paling spesifik lebih dulu.
BUKAN_MENU: dict[str, str] = {
    "Susu formula / MPASI pabrikan": (
        r"susu (sgm|dancow|lactogen|s26|nutrilon|bebelac|morinaga|vitalac|promil|"
        r"sustagen|enfamil|envapro|chilmil|nutrima|llm|bendera)|nestle|milna|promina|"
        r"cerelac|ceresoy|\bsun\b|tepung susu|breastmilk|^puree"
    ),
    "Obat / jamu": r"sirup (batuk|papasetamol|ad plex)|jamu|oralit",
    "Bumbu / rempah / penyedap": (
        r"merica|ketumbar|kunyit|\blaos\b|lengkuas|kayu manis|\bjahe\b|sereh|pandan|"
        r"^salam$|vetsin|^garam|kecap|terasi|buah pala|^kunci$|vanilli|^bumbu|^saos"
    ),
    "Minyak / lemak murni": r"^minyak|gajih|^lemak|mentega|margarin|kethak|^santan",
    "Gula / pemanis": r"^gula|^madu|permen|fruittella|candy|sakarin|^tebu|^setrup|^sirup",
    "Tepung / bahan mentah": (
        r"^tepung|^beras|^adonan|^pati |^katul|^kathul|^ampas|^bungkil|mentah$|"
        r"segar$|^krecek|^campuran beras|^biji|^kulit "
    ),
    "Minuman": (
        r"^teh|^kopi|^jus |^es |^minuman|^air |^larutan|^legen|lemonade|sprite|"
        r"susu (sapi|segar|kambing|skim|kental)|^cincau|^kolang"
    ),
    "Biskuit / snack bermerek": (
        r"^biscuit|^snack|chiki|cheetos|taro|^wafer|astor|milo|ovaltine|^krupuk (fuji|"
        r"jazzy|yeye|monas|boiki|aladin)|dhelco|camel roll|choki|^candy"
    ),
    "Bubur / puree bayi": r"bubur (nestle|sun|serelac|sari buah|nutricia|havermuth|tepung)",
    "Jeroan / darah": (
        r"^hati |^otak|^limfa|^dideh|^usus|^iso |jerohan|^babat|^rempelo|"
        r"^jantung (ayam|itik|menthok|merpati)|^rambak|kikil|^ati |^gajih"
    ),
    "Non-halal / satwa liar": EXCLUDED_FOOD_PATTERN + r"|kelelawar|biawak|tupai|jangkrik|laron|undur-undur|tawon|blekok|kuntul|^keong",

    # --- Di bawah ini ditambahkan setelah memeriksa hasil putaran pertama. ---
    # Penyaring pertama hanya menangkap bahan mentah yang namanya berakhiran
    # "mentah"/"segar"; ternyata sebagian besar bahan mentah di sumber ini tidak
    # memakai penanda apa pun ("kedele kuning", "daging ayam", "ikan kakap").
    "Daging / ikan mentah (bukan hidangan)": (
        r"^daging (?!.*(goreng|bakar|rebus|panggang|semur|rendang))"
        r"|^ikan (?!.*(goreng|bakar|rebus|pindang|asin|cue|pepes|kuah|bumbu|asar|dendeng|balado))"
        r"|^cakalang$|^belut|^udang (segar|kering)$|^kerang$|^cumi-cumi segar"
        r"|^kepiting|^telur (ikan|penyu|puyuh|merpati|menthok|burung|itik|ayam)$"
        r"|^kodok|^bedhek$|^ampal$|^gucang$|tetelan|^kaldu|^rambak"
    ),
    "Kacang / biji / umbi mentah": (
        r"^kacang (hijau|merah|tanah|tolo|mete|dadap|garing|shanghai|kapri|panjang|belimbing|bogor|gude|tunggak|kedelai)"
        r"|^kedele|^kedelai|^koro |^gude$|^cantel$|^gembili|^uwi$|^senthe$|^jengkol$|^petai"
        r"|^kelapa |^kenthos|^wijen$|^kemiri$|^ketapang|^hunkwe$|^mutiara$|^kolang"
        r"|^jagung (kuning|putih|muda)|^ubi jalar (merah|kuning|ungu|putih)$|^kentang( hitam)?$"
        r"|^singkong (kuning|oyek|parut|putih)$|^gaplek$|^blendung|^brondong$|^tebu$"
    ),
    "Buah segar": (
        r"^alpokat$|^alpukat$|^anggur hutan$|^apel$|^arbei$|^asam (mangga|masak)|^belimbing"
        r"|^cerme$|^cimplukan$|^cipleng|^duku$|^durian$|^duwet$|^jambu |^jeruk |^kasreng$"
        r"|^kedondong|^kelengkeng$|^kepel$|^kesemek|^kluwih|^kokosan$|^kurma$|^langsat$"
        r"|^mangga |^manggis$|^matuwa$|^melinjo|^menteng|^nanas$|^nangka |^pepaya|^pisang "
        r"|^rambutan|^salak$|^sawo|^semangka|^sirsak$|^srikaya$|^sukun$|^talok|^pondoh"
        r"|^buah pisang|^gori |^jantung pisang|^kulit melinjo"
    ),
    "Sayur / daun mentah": (
        r"^daun |^bayam (merah|segar)$|^bawang |^bengkuang$|^cabe |^cesim$|^curing|^gambas"
        r"|^genjer|^jamur |^kangkung( mentah)?$|^kembang |^ketimun|^kool |^krai |^labu "
        r"|^lobak|^lompong|^loncang$|^pare |^rebung|^sawi |^selada |^seledri$|^tekokak$"
        r"|^terong |^terung |^tomat |^toge |^uceng$|^waluh|^asparagus|^blusdru$|^bunga "
    ),
    "Kuah saja / bukan hidangan utuh": r"^kuah |^air ",
    # Baris survei konsumsi (akhiran "belu") dan nama terpotong / berlabel harga
    # atau daftar bahan bukan nama menu yang bisa ditampilkan ke pengguna.
    "Nama bukan nama menu": (
        r"\bbelu\b|rp\.|\(terigu|\(tapioka|\(jagung|\(ubi|\(isinya|\(powder\)"
        r"|^arafik$|^kenji$|^halus manis$|^hallo boy|^fujimie|^fuji mie|^bumbu sari"
        # Nama yang terpotong atau rusak di sumber -- tidak layak ditampilkan ke pengguna.
        r"|^martab ak|kacabd|\bsinb\b|kue kontol|^kulit$|^blusdru$|^bedhek$|^cingloy$"
        r"|^loder$|^koya$|^kunci$|^empon$|^gucang$|^orog orog$"
    ),
    # Sisa yang lolos putaran kedua: bahan/olahan setengah jadi, topping, dan
    # bagian telur yang dipisah -- semuanya bukan menu yang bisa disajikan utuh.
    "Bahan / topping / bukan hidangan utuh": (
        r"^temu ireng$|^meises$|^mie soun$|^lamtoro biji|^telur (ikan|itik bagian|ayam bagian)"
        r"|^supermie$|^sarimie$|^misoa$|^makaroni$|^bihun$|^mi golosor$|^mi basah$"
        r"|^choklat$|^coklat$|^coklat (beng|cha)|^jelly$|^miki jelly$|^agar |^agar-agar$"
        r"|^tempe (kedele busuk|koro|lamtoro|gembus)|^kembang tahu|^sagu lempeng$"
        r"|^krecek |^pati |^opak$|^kerupuk terigu|^cake wanderpan$"
    ),
}


def _validitas_fisik(df: pd.DataFrame) -> pd.Series:
    """Alasan penolakan gizi, atau string kosong kalau lolos."""
    massa = df["Protein (g)"] + df["Fat (g)"] + df["Carbohydrates (g)"]
    energi_hitung = df["Protein (g)"] * 4 + df["Fat (g)"] * 9 + df["Carbohydrates (g)"] * 4
    selisih = (df["kcal"] - energi_hitung).abs() / df["kcal"].replace(0, np.nan)

    alasan = pd.Series("", index=df.index)
    alasan[df["kcal"] <= 0] = "energi <= 0"
    alasan[(alasan == "") & (massa > 100)] = "massa makro > 100 g per 100 g"
    alasan[(alasan == "") & (selisih > TOLERANSI_ENERGI)] = (
        f"energi menyimpang > {TOLERANSI_ENERGI:.0%} dari hitungan makro"
    )
    return alasan


def gabungkan(sumber: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Gabungkan dataset menu tambahan ke dataset lama; balas data lama, yang diterima, dan yang ditolak."""
    src = pd.read_csv(sumber)
    lama = pd.read_csv(CSV_TUJUAN)

    src = src.rename(columns={"Menu": "name"})
    src["name"] = src["name"].astype(str).str.strip()
    src["kcal"] = src["Energy (kJ)"] / KJ_PER_KKAL
    nama = src["name"].str.lower()

    alasan = pd.Series("", index=src.index)

    # 1. Bukan menu siap santap.
    for label, pola in BUKAN_MENU.items():
        cocok = (alasan == "") & nama.str.contains(pola, regex=True, na=False)
        alasan[cocok] = label

    # 2. Nilai gizi tidak masuk akal.
    fisik = _validitas_fisik(src)
    alasan[(alasan == "") & (fisik != "")] = fisik[(alasan == "") & (fisik != "")]

    # 3. Nama bentrok dengan dataset lama -> dataset lama menang.
    nama_lama = set(lama["name"].astype(str).str.lower().str.strip())
    alasan[(alasan == "") & nama.isin(nama_lama)] = "nama sudah ada di dataset lama"

    # 4. Nama ganda di dalam sumber itu sendiri -> ambil kemunculan pertama.
    ganda = nama.duplicated(keep="first")
    alasan[(alasan == "") & ganda] = "nama ganda di dalam sumber"

    diterima = src[alasan == ""].copy()
    ditolak = src[alasan != ""].copy()
    ditolak["alasan"] = alasan[alasan != ""]

    # Bentuk baris baru mengikuti skema dataset tujuan.
    id_mulai = int(pd.to_numeric(lama["id"], errors="coerce").max()) + 1
    baru = pd.DataFrame({
        "id": range(id_mulai, id_mulai + len(diterima)),
        "calories": diterima["kcal"].round().astype(int).values,
        "proteins": diterima["Protein (g)"].values,
        "fat": diterima["Fat (g)"].values,
        "carbohydrate": diterima["Carbohydrates (g)"].values,
        "name": diterima["name"].values,
        # Sumbernya tidak menyediakan gambar. Dibiarkan kosong, bukan diisi
        # tautan karangan yang belum tentu ada.
        "image": "",
    })
    return lama, baru, ditolak


def main() -> int:
    """Jalankan penggabungan dari baris perintah, tampilkan ringkasannya, lalu simpan bila diminta."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sumber", required=True, help="path foods.csv")
    p.add_argument("--tulis", action="store_true", help="simpan ke food_nutrition.csv")
    p.add_argument("--db", action="store_true", help="sisipkan juga ke tabel food_nutrition")
    a = p.parse_args()

    lama, baru, ditolak = gabungkan(Path(a.sumber))

    print(f"Dataset lama       : {len(lama)} baris")
    print(f"Sumber tambahan    : {len(baru) + len(ditolak)} baris")
    print(f"  diterima         : {len(baru)}")
    print(f"  ditolak          : {len(ditolak)}\n")
    print("Alasan penolakan:")
    for alasan, jumlah in ditolak["alasan"].value_counts().items():
        print(f"  {alasan:48s} {jumlah:4d}")
    print(f"\nTotal setelah digabung: {len(lama) + len(baru)} baris")

    print("\nContoh baris yang diterima:")
    for _, r in baru.head(15).iterrows():
        print(f"  {r['name'][:40]:42s} {r['calories']:4d} kkal  "
              f"P{r['proteins']:5.1f} L{r['fat']:5.1f} K{r['carbohydrate']:5.1f}")

    if not a.tulis:
        print("\n(pratinjau saja -- jalankan ulang dengan --tulis untuk menyimpan)")
        return 0

    gabungan = pd.concat([lama, baru], ignore_index=True)
    gabungan.to_csv(CSV_TUJUAN, index=False)
    baru.to_csv(LAPORAN, index=False)
    ditolak[["name", "alasan"]].to_csv(DIBUANG, index=False)
    print(f"\nCSV diperbarui  : {CSV_TUJUAN}  ({len(gabungan)} baris)")
    print(f"Baris baru      : {LAPORAN}")
    print(f"Baris ditolak   : {DIBUANG}")

    if a.db:
        from src.database import SQLStore
        store = SQLStore()
        with store.connection() as koneksi:
            with koneksi.cursor() as kursor:
                ph = store.placeholder()
                for _, r in baru.iterrows():
                    kursor.execute(
                        f"INSERT INTO food_nutrition (id, calories, proteins, fat, "
                        f"carbohydrate, name, image) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                        (int(r["id"]), float(r["calories"]), float(r["proteins"]),
                         float(r["fat"]), float(r["carbohydrate"]), r["name"], r["image"]),
                    )
        print(f"Baris disisipkan ke database: {len(baru)}")
    else:
        print("Database belum disentuh. Tambahkan --db bila ingin sekalian.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
