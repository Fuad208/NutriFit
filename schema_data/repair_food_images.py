"""Perbaiki URL gambar menu yang sudah mati, sumbernya Wikimedia Commons.

MASALAHNYA. URL gambar di dataset menunjuk ke CDN pihak ketiga (Tokopedia, Kompas,
Detik, blog resep). Tautan seperti itu lapuk: saat skrip ini dibuat, 63 dari 260 menu
yang layak direkomendasikan sudah kehilangan gambarnya. Aplikasi membuang menu yang
gambarnya tidak bisa ditampilkan, jadi tiap tautan mati mengurangi jumlah menu yang
bisa direkomendasikan -- dan membuat jumlah baris pada laporan penelitian berubah-ubah
tergantung kapan dijalankan.

KENAPA WIKIMEDIA COMMONS. Berlisensi bebas (tidak ada masalah ketentuan layanan seperti
scraping marketplace), URL-nya stabil di `upload.wikimedia.org`, punya API resmi, dan
domain itu memang sudah menjadi salah satu sumber gambar terbanyak di dataset ini.

CARA PAKAI:
    python schema_data/repair_food_images.py                 # pratinjau, tidak menulis
    python schema_data/repair_food_images.py --tulis         # perbarui CSV
    python schema_data/repair_food_images.py --tulis --db    # perbarui CSV + database
    python schema_data/repair_food_images.py --semua         # sisir seluruh 1.346 baris

Yang TIDAK dilakukan skrip ini: mengarang nilai gizi. Ia hanya menyentuh kolom `image`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd  # noqa: E402

from src.recommender import (  # noqa: E402
    filter_recommendable_foods,
    image_url_is_displayable,
)

CSV_PATH = ROOT_DIR / "data" / "food_nutrition.csv"
LAPORAN_PATH = ROOT_DIR / "data" / "perbaikan_gambar.csv"

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia meminta User-Agent yang menyebut identitas & kontak pemakainya.
USER_AGENT = "NutriFit-ImageRepair/1.0 (proyek akhir akademik; kontak lewat repositori)"
JEDA_DETIK = 3.0          # Wikimedia membatasi laju API pencarian cukup ketat
LEBAR_THUMBNAIL = 500

# Kata yang menerangkan cara masak / bagian / asal daerah. Dibuang bertahap saat
# pencarian nama lengkap tidak membuahkan hasil, karena Commons hampir tidak pernah
# punya berkas bernama "ayam goreng sukabumi paha" tapi hampir pasti punya "ayam goreng".
KATA_PELENGKAP = {
    "masakan", "segar", "mentah", "kukus", "rebus", "bakar", "goreng", "tumis",
    "dada", "paha", "sayap", "utuh", "berkulit", "tanpa", "dengan", "dan",
    "manis", "asin", "tebal", "tipis", "besar", "kecil", "muda", "tua",
    "kuning", "merah", "hitam", "putih", "hijau", "bertepung", "instan",
}

# Panjang minimum kata yang ikut dinilai. Tiga, bukan empat: kata pembeda seperti
# "tim" pada "nasi tim" hanya tiga huruf, dan tanpa itu "Nasi Kuning" terlihat
# sama cocoknya dengan "Nasi tim".
PANJANG_TOKEN_MINIMUM = 3

# Kata sambung / penanda yang tidak membawa informasi apa pun saat mencocokkan.
KATA_ABAIKAN = {
    "tanpa", "dengan", "dan", "atau", "yang", "dari", "untuk", "masakan",
    "file", "jpg", "jpeg", "png", "the", "and", "for", "with",
}

# Berapa banyak kata nama menu yang minimal harus muncul di nama berkas.
# Satu kata saja terbukti tidak cukup: "Kerupuk Melinjo" mendarat di "Kerupuk kulit
# sapi", "Kacang Kedelai" di "Kacang Amazon", dan "Sayur kohu-kohu" di "Sayur Asem
# Betawi" -- semuanya berbagi tepat satu kata yang terlalu umum.
MINIMAL_KATA_COCOK = 2

# Hanya foto. Commons menandai pindaian buku .djvu sebagai "image/vnd.djvu", jadi
# memeriksa awalan "image/" saja meloloskan buku resep TTG MASAKAN INDONESIA
# sebagai "gambar" untuk rawon dan teri balado.
MIME_DIIZINKAN = {"image/jpeg", "image/png", "image/webp"}

# Berkas yang kategorinya menyebut ini ditolak walaupun tema besarnya makanan:
# perangko bergambar soto tetap perangko, bukan foto soto.
KATEGORI_BUKAN_FOTO = re.compile(
    r"stamp|postage|philatel|coin|banknote|currency|book|scan|djvu|logo|map|poster|"
    r"drawing|illustration|painting|engraving|diagram|cover|perangko|lukisan|buku",
    re.IGNORECASE,
)

# Nama JENIS HIDANGAN. Dipakai sebagai penjaga: kalau berkas Commons menyebut jenis
# hidangan yang TIDAK ada di nama menu, berkas itu ditolak. Tanpa aturan ini
# "Ayam goreng sukabumi" mendarat di "Bubur Ayam Sukabumi" -- sama-sama ayam dan
# sama-sama Sukabumi, tapi bubur, bukan ayam goreng.
JENIS_HIDANGAN = {
    "bubur", "soto", "sate", "rendang", "gulai", "nasi", "mie", "bihun", "bakso",
    "gado", "pempek", "rawon", "opor", "semur", "kari", "coto", "botok", "pepes",
    "asinan", "rujak", "ketoprak", "siomay", "batagor", "empal", "dendeng", "abon",
    "kerupuk", "keripik", "lontong", "ketupat", "gudeg", "pecel", "karedok", "urap",
    "perkedel", "nugget", "getuk", "pempek", "tumis", "balado", "sambal", "kolak",
    "soup", "salad", "porridge", "noodle", "noodles", "satay", "curry",
}

# Berkas Commons dianggap makanan kalau salah satu kategorinya menyebut kata ini.
# Diuji langsung ke API: "Gereja Ayam" (bangunan gereja berbentuk ayam) tidak punya
# satu pun kategori seperti ini, sedangkan "Gado-gado" masuk "Food of Indonesia".
KATEGORI_MAKANAN = re.compile(
    r"cuisine|food|dish|dessert|beverage|drink|snack|soup|salad|noodle|rice|meat|"
    r"seafood|fish|fruit|vegetable|cake|bread|pastry|cooking|cooked|breakfast|"
    r"masakan|makanan|kuliner|minuman|hidangan|jajanan|kue",
    re.IGNORECASE,
)


def bersihkan_nama(nama: str) -> list[str]:
    """Ubah satu nama menu jadi daftar kueri, dari paling spesifik ke paling umum."""
    teks = str(nama or "").lower().strip()
    teks = re.sub(r"\(.*?\)", " ", teks)          # buang keterangan dalam kurung
    teks = re.sub(r"[/,]+", " ", teks)
    teks = re.sub(r"[^a-z0-9\s-]", " ", teks)
    token = [t for t in teks.split() if t]
    if not token:
        return []

    inti = [t for t in token if t not in KATA_PELENGKAP]
    kueri: list[str] = []

    def tambah(kandidat: list[str]) -> None:
        """Tambahkan satu frasa kueri ke daftar bila belum ada dan tidak kosong."""
        frasa = " ".join(kandidat).strip()
        if frasa and frasa not in kueri:
            kueri.append(frasa)

    tambah(token)                 # nama utuh
    tambah(inti)                  # tanpa kata pelengkap
    if len(inti) > 2:
        tambah(inti[:2])
    if inti:
        tambah(inti[:1])          # bahan utamanya saja
    return kueri


def token_bermakna(nama: str) -> set[str]:
    """Kata penanda isi, dipakai untuk MENILAI kecocokan.

    Cara masak (goreng/rebus/bakar) sengaja TIDAK dibuang di sini walaupun dibuang
    saat menyusun kueri: "ayam goreng" dan "bubur ayam" sama-sama ayam, dan justru
    kata cara masak itulah yang membedakannya.
    """
    teks = re.sub(r"[^a-z0-9\s]", " ", str(nama).lower())
    return {
        t for t in teks.split()
        if len(t) >= PANJANG_TOKEN_MINIMUM and t not in KATA_ABAIKAN
    }


def _semua_kata(teks: str) -> set[str]:
    """Seluruh kata, TANPA batas panjang minimum."""
    return set(re.sub(r"[^a-z0-9\s]", " ", str(teks).lower()).split())


def hidangan_bertabrakan(judul_berkas: str, nama_menu: str) -> bool:
    """True kalau berkas menyebut JENIS hidangan yang tidak ada di nama menu.

    Sengaja memakai _semua_kata, bukan token_bermakna: jenis hidangan terpendek
    ("mie", "sup", "kue") hanya tiga huruf dan akan lolos dari batas panjang
    minimum. Karena celah itu, "Ayam goreng sukabumi" sempat mendapat gambar
    "Mie ayam lima ribu rupiah".
    """
    di_berkas = _semua_kata(judul_berkas) & JENIS_HIDANGAN
    di_menu = _semua_kata(nama_menu) & JENIS_HIDANGAN
    return bool(di_berkas - di_menu)


def kategori_berkas(judul: list[str]) -> dict[str, list[str]]:
    """Ambil kategori beberapa berkas Commons sekaligus (satu permintaan per 50 judul)."""
    from urllib.request import Request, urlopen

    hasil: dict[str, list[str]] = {}
    for mulai in range(0, len(judul), 50):
        potongan = judul[mulai:mulai + 50]
        parameter = {
            "action": "query",
            "titles": "|".join(potongan),
            "prop": "categories",
            "cllimit": "max",
            "format": "json",
        }
        url = f"{COMMONS_API}?{urllib.parse.urlencode(parameter)}"
        permintaan = Request(url, headers={"User-Agent": USER_AGENT})
        _jeda_sopan()
        try:
            with urlopen(permintaan, timeout=20) as tanggapan:
                data = json.loads(tanggapan.read().decode("utf-8"))
        except Exception:
            continue
        for isi in ((data.get("query") or {}).get("pages") or {}).values():
            hasil[isi.get("title", "")] = [
                str(k.get("title", "")).replace("Category:", "")
                for k in (isi.get("categories") or [])
            ]
    return hasil


def berkas_tentang_makanan(kategori: list[str]) -> bool:
    """True bila kategori berkas Commons menandakan foto makanan, bukan ilustrasi atau logo."""
    if any(KATEGORI_BUKAN_FOTO.search(k) for k in kategori):
        return False
    return any(KATEGORI_MAKANAN.search(k) for k in kategori)


class CommonsTidakTersedia(RuntimeError):
    """API Commons menolak permintaan (rate limit / gangguan), bukan 'tidak ada hasil'."""


_waktu_permintaan_terakhir = 0.0


def _jeda_sopan() -> None:
    """Beri jarak antar-permintaan supaya tidak kena pembatasan laju."""
    global _waktu_permintaan_terakhir
    selisih = time.monotonic() - _waktu_permintaan_terakhir
    if selisih < JEDA_DETIK:
        time.sleep(JEDA_DETIK - selisih)
    _waktu_permintaan_terakhir = time.monotonic()


def cari_commons(kueri: str, batas: int = 10, percobaan: int = 3) -> list[dict]:
    """Cari berkas gambar di Commons. Mengembalikan daftar {judul, url}.

    Kegagalan jaringan SENGAJA tidak diubah jadi daftar kosong. Versi pertama skrip
    ini menelan semua exception, sehingga permintaan yang ditolak karena pembatasan
    laju terbaca persis seperti "Commons tidak punya gambarnya" -- dan 'gado-gado'
    yang jelas-jelas ada di Commons dilaporkan tidak ketemu.
    """
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    parameter = {
        "action": "query",
        "generator": "search",
        "gsrsearch": kueri,
        "gsrnamespace": "6",          # namespace berkas
        "gsrlimit": str(batas),
        "prop": "imageinfo",
        "iiprop": "url|mime",
        "iiurlwidth": str(LEBAR_THUMBNAIL),
        "format": "json",
    }
    url = f"{COMMONS_API}?{urllib.parse.urlencode(parameter)}"
    permintaan = Request(url, headers={"User-Agent": USER_AGENT})

    for percobaan_ke in range(percobaan):
        _jeda_sopan()
        try:
            with urlopen(permintaan, timeout=20) as tanggapan:
                data = json.loads(tanggapan.read().decode("utf-8"))
            break
        except HTTPError as galat:
            if galat.code in {429, 500, 502, 503, 504} and percobaan_ke < percobaan - 1:
                time.sleep(5 * (percobaan_ke + 1) ** 2)   # mundur: 5s, 20s
                continue
            raise CommonsTidakTersedia(f"HTTP {galat.code} untuk kueri '{kueri}'") from galat
        except (URLError, TimeoutError, OSError, ValueError) as galat:
            if percobaan_ke < percobaan - 1:
                time.sleep(5 * (percobaan_ke + 1) ** 2)
                continue
            raise CommonsTidakTersedia(f"{type(galat).__name__} untuk kueri '{kueri}'") from galat
    else:
        raise CommonsTidakTersedia(f"gagal setelah {percobaan} percobaan: '{kueri}'")

    halaman = (data.get("query") or {}).get("pages") or {}
    hasil = []
    for isi in halaman.values():
        info = (isi.get("imageinfo") or [{}])[0]
        if str(info.get("mime", "")).lower() not in MIME_DIIZINKAN:
            continue
        alamat = info.get("thumburl") or info.get("url")
        if alamat:
            hasil.append({"judul": isi.get("title", ""), "url": alamat})
    return hasil


def cari_gambar_pengganti(nama_menu: str) -> tuple[str, str] | None:
    """URL gambar Commons paling cocok yang terbukti bisa ditampilkan, atau None.

    Seluruh kandidat dari semua tingkat kueri dikumpulkan lalu DIPERINGKAT menurut
    berapa banyak kata nama menu yang muncul di nama berkasnya. Mengambil kandidat
    pertama yang "lumayan" membuat menu spesifik seperti "Bihun goreng" bisa
    mendarat di gambar bihun rebus biasa hanya karena berkas itu muncul lebih dulu.
    """
    diharapkan = token_bermakna(nama_menu)
    if not diharapkan:
        return None

    # Menu bernama satu kata ("Gado-gado", "Sukiyaki") memang hanya bisa dicocokkan
    # dengan satu kata; sisanya wajib cocok minimal dua supaya kesamaan pada satu
    # kata umum saja tidak cukup untuk lolos.
    wajib_cocok = min(MINIMAL_KATA_COCOK, len(diharapkan))

    kandidat: list[tuple[int, int, str, str]] = []
    for tingkat, kueri in enumerate(bersihkan_nama(nama_menu)[:3]):
        for hasil in cari_commons(kueri):
            tumpang_tindih = token_bermakna(hasil["judul"]) & diharapkan
            if len(tumpang_tindih) < wajib_cocok:
                continue
            # Jenis hidangan yang bertabrakan langsung digugurkan, berapa pun
            # kata lain yang cocok.
            if hidangan_bertabrakan(hasil["judul"], nama_menu):
                continue
            # Skor: makin banyak kata cocok makin baik; kueri yang lebih spesifik
            # (tingkat lebih kecil) menang saat jumlah kata cocoknya sama.
            kandidat.append((len(tumpang_tindih), -tingkat, hasil["url"], hasil["judul"]))
        if any(skor >= len(diharapkan) for skor, *_ in kandidat):
            break

    if not kandidat:
        return None

    kandidat.sort(reverse=True)
    kandidat = kandidat[:8]

    # Saring dengan kategori Commons: berkas harus benar-benar tentang makanan.
    # Pencocokan kata saja pernah meloloskan "Gereja Ayam" -- bangunan gereja
    # berbentuk ayam -- sebagai gambar untuk menu ayam goreng.
    peta_kategori = kategori_berkas([judul for *_, judul in kandidat])
    for _, _, alamat, judul in kandidat:
        if not berkas_tentang_makanan(peta_kategori.get(judul, [])):
            continue
        if image_url_is_displayable(alamat):
            return alamat, judul
    return None


def baris_yang_direkomendasikan(df: pd.DataFrame) -> pd.Series:
    """Baris yang benar-benar bisa direkomendasikan aplikasi.

    Memanggil filter milik aplikasi, bukan menyalin polanya. Versi lama menyusun
    ulang kondisinya sendiri, dan begitu aturan kelayakan berubah skrip ini
    memperbaiki gambar untuk kumpulan baris yang berbeda dari yang dipakai
    produk.
    """
    layak = filter_recommendable_foods(df)
    return df.index.isin(layak.index)


def perbarui_database(perubahan: pd.DataFrame) -> int:
    """Tulis URL baru ke tabel food_nutrition. Hanya kolom image yang disentuh."""
    from src.database import SQLStore

    store = SQLStore()
    with store.connection() as koneksi:
        with koneksi.cursor() as kursor:
            for _, baris in perubahan.iterrows():
                kursor.execute(
                    f"UPDATE food_nutrition SET image = {store.placeholder()} "
                    f"WHERE id = {store.placeholder()}",
                    (baris["image_baru"], int(baris["id"])),
                )
    return len(perubahan)


def main() -> int:
    """Cari gambar pengganti untuk menu yang tautannya mati, lalu simpan ke CSV atau database bila diminta."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tulis", action="store_true", help="simpan hasil ke CSV")
    parser.add_argument("--db", action="store_true", help="perbarui juga tabel food_nutrition")
    parser.add_argument("--semua", action="store_true", help="sisir seluruh baris, bukan hanya yang direkomendasikan")
    parser.add_argument("--batas", type=int, default=0, help="hentikan setelah N menu (untuk uji coba)")
    argumen = parser.parse_args()

    df = pd.read_csv(CSV_PATH)
    target = df if argumen.semua else df[baris_yang_direkomendasikan(df)]
    print(f"Memeriksa {len(target)} dari {len(df)} baris dataset...")

    perlu_diperbaiki = []
    for indeks, baris in target.iterrows():
        alamat = str(baris.get("image") or "")
        if not image_url_is_displayable(alamat):
            perlu_diperbaiki.append(indeks)
    print(f"Gambar mati / kosong: {len(perlu_diperbaiki)}\n")

    if argumen.batas:
        perlu_diperbaiki = perlu_diperbaiki[: argumen.batas]

    catatan = []
    for urutan, indeks in enumerate(perlu_diperbaiki, start=1):
        nama = str(df.at[indeks, "name"])
        try:
            hasil = cari_gambar_pengganti(nama)
        except CommonsTidakTersedia as galat:
            # Dibedakan dari "tidak ketemu": ini gangguan sementara, dan menu ini
            # masih bisa diperbaiki kalau skrip dijalankan lagi nanti.
            print(f"  [{urutan:3d}/{len(perlu_diperbaiki)}] GAGAL AKSES   {nama}  ({galat})")
            continue
        if hasil is None:
            print(f"  [{urutan:3d}/{len(perlu_diperbaiki)}] TIDAK KETEMU  {nama}")
            continue
        alamat_baru, kueri = hasil
        catatan.append(
            {
                "id": df.at[indeks, "id"],
                "name": nama,
                "berkas_commons": kueri,
                "image_lama": df.at[indeks, "image"],
                "image_baru": alamat_baru,
            }
        )
        df.at[indeks, "image"] = alamat_baru
        print(f"  [{urutan:3d}/{len(perlu_diperbaiki)}] OK  {nama}  <- '{kueri}'")

    perubahan = pd.DataFrame(catatan)
    print(f"\nBerhasil diperbaiki: {len(perubahan)} dari {len(perlu_diperbaiki)}")

    if perubahan.empty:
        return 0

    if not argumen.tulis:
        print("\n(pratinjau saja -- jalankan ulang dengan --tulis untuk menyimpan)")
        return 0

    df.to_csv(CSV_PATH, index=False)
    perubahan.to_csv(LAPORAN_PATH, index=False)
    print(f"CSV diperbarui   : {CSV_PATH}")
    print(f"Laporan perubahan: {LAPORAN_PATH}")

    if argumen.db:
        jumlah = perbarui_database(perubahan)
        print(f"Baris database diperbarui: {jumlah}")
    else:
        print("Database belum disentuh. Tambahkan --db, atau jalankan ulang import_csv_to_db.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
