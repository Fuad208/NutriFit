"""Uji pemeriksa gambar: membedakan tautan mati dari pembatasan laju host.

Menjaga sifat yang membuat jumlah menu bisa direproduksi.
"""
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(r"c:\Kuliah\Semester 8\Tugas Akhir\Coding\NutriFit")
sys.path.insert(0, str(ROOT))

import src.recommender as R  # noqa: E402


def galat(kode: int) -> HTTPError:
    """Bentuk HTTPError tiruan dengan kode status tertentu."""
    return HTTPError("https://contoh/a.jpg", kode, "galat", {}, None)


def bersihkan() -> None:
    """Kosongkan cache pemeriksaan gambar agar tiap kasus uji berdiri sendiri."""
    R.image_url_is_displayable.cache_clear()
    R._THROTTLED_URLS.clear()


print("== kode 'server sibuk' dipertahankan, kode 'tidak ada' dibuang ==")
for kode, harap in [(429, True), (500, True), (502, True), (503, True), (504, True),
                    (404, False), (410, False), (400, False)]:
    bersihkan()
    with patch("src.recommender.urlopen", side_effect=galat(kode)):
        hasil = R.image_url_is_displayable(f"https://contoh/{kode}.jpg")
    assert hasil == harap, f"HTTP {kode} seharusnya {harap}, dapat {hasil}"
    dicatat = len(R._THROTTLED_URLS) > 0
    assert dicatat == (kode in R.THROTTLED_STATUS)
    print(f"   HTTP {kode:3d} -> tampilkan={hasil!s:5s} dicatat_throttle={dicatat}")

print("\n== hasil throttle TIDAK ditulis ke cache disk ==")
bersihkan()
disimpan: dict = {}
with patch("src.recommender.urlopen", side_effect=galat(429)), \
     patch("src.recommender._load_image_cache", return_value={}), \
     patch("src.recommender._save_image_cache", side_effect=disimpan.update):
    hasil = R.check_image_urls_concurrently(["https://contoh/a.jpg", "https://contoh/b.jpg"])
assert hasil == [True, True], hasil
assert disimpan == {}, f"dugaan optimistis ikut tersimpan: {disimpan}"
print(f"   dikembalikan {hasil} tetapi cache disk tetap kosong -> diperiksa lagi lain kali")

print("\n== gambar yang benar-benar mati TETAP disimpan ==")
bersihkan()
disimpan = {}
with patch("src.recommender.urlopen", side_effect=galat(404)), \
     patch("src.recommender._load_image_cache", return_value={}), \
     patch("src.recommender._save_image_cache", side_effect=disimpan.update):
    hasil = R.check_image_urls_concurrently(["https://contoh/c.jpg"])
assert hasil == [False]
assert disimpan == {"https://contoh/c.jpg": False}, disimpan
print(f"   dikembalikan {hasil} dan tersimpan {disimpan}")

print("\n== 403/405 tetap dicoba ulang dengan GET (perilaku lama dipertahankan) ==")
bersihkan()
with patch("src.recommender.urlopen", side_effect=galat(403)), \
     patch("src.recommender.image_url_is_displayable_with_get", return_value=True) as get:
    hasil = R.image_url_is_displayable("https://contoh/d.jpg")
assert hasil is True and get.called
print("   403 -> dicoba ulang lewat GET")

print("\n== URL bukan http tetap ditolak tanpa menyentuh jaringan ==")
bersihkan()
for buruk in ["", "ftp://x/a.jpg", "bukan-url", None]:
    assert R.image_url_is_displayable(buruk) is False
print("   URL kosong / skema salah ditolak")

print("\n== status gambar dibaca dari cache, TANPA jaringan ==")
bersihkan()
with patch("src.recommender._load_image_cache",
           return_value={"https://ada/a.jpg": True, "https://mati/b.jpg": False}), \
     patch("src.recommender.urlopen", side_effect=AssertionError("menyentuh jaringan!")):
    status = R.image_status_from_cache([
        "https://ada/a.jpg",        # tercatat hidup
        "https://mati/b.jpg",       # tercatat mati
        "https://belum/c.jpg",      # belum pernah dicek -> optimistis
        "",                         # kosong
        "bukan-url",                # skema salah
    ])
assert status == [True, False, True, False, False], status
print(f"   {status}  (belum pernah dicek -> True, tanpa satu pun permintaan)")

print("\n== menu TIDAK lagi dibuang karena gambarnya mati ==")
import pandas as pd  # noqa: E402

# Nilai gizinya sengaja dibuat konsisten dengan faktor Atwater (4-9-4), karena
# filter kelayakan sekarang JUGA menolak baris yang energinya tidak masuk akal.
# Uji ini soal gambar, jadi datanya tidak boleh gagal karena alasan lain.
contoh = pd.DataFrame({
    "id": [1, 2, 3],
    "name": ["Nasi goreng", "Ayam goreng", "Soto ayam"],
    "calories": [230, 223, 88],
    "proteins": [5.0, 20.0, 8.0],
    "fat": [10.0, 15.0, 4.0],
    "carbohydrate": [30.0, 2.0, 5.0],
    "image": ["https://mati/x.jpg", "", "https://ada/y.jpg"],
})
with patch("src.recommender._load_image_cache",
           return_value={"https://mati/x.jpg": False, "https://ada/y.jpg": True}), \
     patch("src.recommender.urlopen", side_effect=AssertionError("menyentuh jaringan!")):
    hasil = R.filter_recommendable_foods(contoh)
assert len(hasil) == 3, f"menu terbuang gara-gara gambar: {len(hasil)}/3"
assert list(hasil["Has_Image"]) == [False, False, True], list(hasil["Has_Image"])
print(f"   ketiga menu dipertahankan; Has_Image = {list(hasil['Has_Image'])}")

print("\n== kartu memakai gambar pengganti dengan aman ==")
from src.views.meal import meal_image_html  # noqa: E402

assert "<img" in meal_image_html({"image": "https://x/a.jpg", "Has_Image": True})
assert "<img" not in meal_image_html({"image": "https://x/b.jpg", "Has_Image": False})
assert "<img" not in meal_image_html({"image": "", "Has_Image": False})
assert "<img" not in meal_image_html({"image": float("nan"), "Has_Image": True})
# Record lama belum punya kolom Has_Image -- diperlakukan optimistis.
assert "<img" in meal_image_html({"image": "https://x/c.jpg"})
assert "<img" not in meal_image_html({"image": ""})
# Nilai dari database tidak boleh bisa menyuntik atribut HTML.
nakal = meal_image_html({"image": 'https://x/a.jpg" onerror="alert(1)', "Has_Image": True})
assert 'onerror="' not in nakal and "&quot;" in nakal, nakal
print("   valid -> <img>; mati/kosong -> pengganti; kutip ganda ter-escape")

print("\n== masa berlaku cache 90 hari ==")
assert R.IMAGE_CACHE_TTL_SECONDS == 90 * 24 * 60 * 60, R.IMAGE_CACHE_TTL_SECONDS
print(f"   {R.IMAGE_CACHE_TTL_SECONDS // 86400} hari")

print("\nSEMUA ASSERT PEMERIKSA GAMBAR LOLOS")
