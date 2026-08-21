"""Unduh aset animasi Lottie & mesin pemutarnya ke folder assets/.

Dijalankan SEKALI saat menyiapkan proyek, bukan saat aplikasi berjalan. Hasil
unduhannya ikut disimpan di repositori supaya aplikasi tidak pernah menyentuh
jaringan hanya untuk menampilkan halaman login -- alasannya sama dengan kamus
terjemahan di data/exercise_id_lexicon.json: hasil harus sama persis di setiap
mesin, termasuk mesin penguji yang mungkin offline.

Jalankan:
    .venv/Scripts/python.exe schema_data/fetch_lottie_assets.py

Sumber & lisensi tercatat di assets/lottie/SUMBER.md.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
LOTTIE_DIR = ASSETS_DIR / "lottie"
VENDOR_DIR = ASSETS_DIR / "vendor"

# User-Agent peramban sungguhan: lottiefiles.com berada di belakang Cloudflare
# dan menolak UA bawaan curl dengan halaman tantangan "Just a moment...".
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# lottie_light: varian tanpa dukungan ekspresi & efek, ~40% lebih kecil dari
# lottie.min.js dan sudah cukup untuk animasi bentuk biasa.
PEMUTAR_URL = (
    "https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie_light.min.js"
)

# Halaman animasi -> nama berkas tujuan. URL .lottie-nya TIDAK ditulis langsung
# karena bisa berubah; yang stabil adalah slug halamannya, jadi URL aset dibaca
# ulang dari halaman itu setiap kali skrip ini dijalankan.
ANIMASI = {
    "hero_login": "t-plank-exercise-g5qVU6RPYY",
    "hero_register": "jumping-squats-9hzVV8Ohi6",
}

POLA_ASET = re.compile(
    r"https://assets-v2\.lottiefiles\.com/a/[A-Za-z0-9-]+/[A-Za-z0-9]+\.lottie"
)


def unduh(url: str) -> bytes:
    """Ambil satu URL lewat curl; gagal berarti berhenti dengan pesan jelas."""
    hasil = subprocess.run(
        ["curl", "-sSL", "--fail", "--max-time", "60", "-A", UA, url],
        capture_output=True,
    )
    if hasil.returncode != 0 or not hasil.stdout:
        pesan = hasil.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(f"Gagal mengunduh {url}\n  {pesan}")
    return hasil.stdout


def bulatkan(node, digit: int = 3):
    """Pangkas presisi float di seluruh pohon JSON.

    Lottie hasil ekspor menyimpan koordinat dengan 10+ angka desimal, dan itu
    bisa separuh isi berkasnya. Tiga desimal jauh di bawah ambang satu piksel
    pada kanvas 1000px, jadi tidak ada bedanya di mata -- tapi berkasnya
    menyusut banyak, dan berkas ini disisipkan ke HTML pada SETIAP render
    halaman login, sehingga ukurannya terasa.
    """
    if isinstance(node, float):
        dibulatkan = round(node, digit)
        # Simpan sebagai int kalau memang bulat: "1" lebih pendek dari "1.0".
        return int(dibulatkan) if dibulatkan == int(dibulatkan) else dibulatkan
    if isinstance(node, dict):
        return {k: bulatkan(v, digit) for k, v in node.items()}
    if isinstance(node, list):
        return [bulatkan(v, digit) for v in node]
    return node


def ambil_animasi(slug: str) -> tuple[dict, str]:
    """Kembalikan (animasi, url_aset) dari satu halaman animasi LottieFiles."""
    halaman = unduh(f"https://lottiefiles.com/free-animation/{slug}")
    cocok = POLA_ASET.search(halaman.decode("utf-8", "replace"))
    if not cocok:
        raise SystemExit(
            f"URL .lottie tidak ditemukan di halaman '{slug}'. "
            "Kemungkinan tata letak situsnya berubah; periksa manual."
        )
    url = cocok.group(0)

    # Berkas .lottie adalah arsip ZIP berisi manifest + animations/*.json.
    arsip = zipfile.ZipFile(io.BytesIO(unduh(url)))
    isi = [n for n in arsip.namelist() if n.startswith("animations/")]
    if not isi:
        raise SystemExit(f"Arsip {url} tidak memuat folder animations/")
    return json.loads(arsip.read(isi[0])), url


def periksa(anim: dict, nama: str) -> None:
    """Pastikan animasi utuh SEBELUM ditulis ke assets/.

    Berkas yang lolos ke repositori tapi ternyata cacat hanya akan terlihat
    sebagai kotak kosong di halaman login, tanpa pesan kesalahan apa pun --
    jadi lebih baik gagal di sini, saat penyebabnya masih jelas.
    """
    wajib = ("v", "fr", "ip", "op", "w", "h", "layers")
    hilang = [k for k in wajib if k not in anim]
    if hilang:
        raise SystemExit(f"{nama}: kunci wajib tidak ada -> {hilang}")
    if not anim["layers"]:
        raise SystemExit(f"{nama}: tidak punya lapisan sama sekali")
    luar = [
        a.get("p")
        for a in anim.get("assets", [])
        if a.get("p") and not str(a.get("p")).startswith("data:")
    ]
    if luar:
        # Aset raster eksternal akan gagal dimuat di dalam iframe komponen
        # Streamlit (tidak ada server yang menyajikannya), jadi animasinya
        # tampil rusak sebagian tanpa error yang kelihatan.
        raise SystemExit(f"{nama}: memuat gambar eksternal {luar[:3]}")


def main() -> None:
    """Unduh pemutar Lottie dan seluruh animasi, periksa, padatkan, lalu simpan ke folder assets."""
    LOTTIE_DIR.mkdir(parents=True, exist_ok=True)
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)

    pemutar = VENDOR_DIR / "lottie_light.min.js"
    pemutar.write_bytes(unduh(PEMUTAR_URL))
    print(f"pemutar  {pemutar.name}: {pemutar.stat().st_size // 1024} KB")

    catatan = []
    for nama, slug in ANIMASI.items():
        anim, url = ambil_animasi(slug)
        periksa(anim, nama)
        padat = json.dumps(bulatkan(anim), separators=(",", ":"))
        tujuan = LOTTIE_DIR / f"{nama}.json"
        tujuan.write_text(padat, encoding="utf-8")
        print(
            f"animasi  {tujuan.name}: {len(padat) // 1024} KB "
            f"({anim['w']}x{anim['h']}, {len(anim['layers'])} lapisan)"
        )
        catatan.append((nama, slug, url, anim))

    tulis_sumber(catatan)


def tulis_sumber(catatan) -> None:
    """Catat asal berkas supaya bisa dipertanggungjawabkan di laporan."""
    baris = [
        "# Sumber aset animasi",
        "",
        "Berkas di folder ini TIDAK dibuat sendiri. Semuanya diunduh ulang oleh",
        "`schema_data/fetch_lottie_assets.py`; jangan disunting manual, karena",
        "suntingan akan hilang saat skrip itu dijalankan lagi.",
        "",
        "## Animasi",
        "",
        "Diambil dari koleksi **free animations** LottieFiles, yang berlisensi",
        "[Lottie Simple License (FL 9.13.21)](https://lottiefiles.com/page/license):",
        "bebas dipakai untuk keperluan pribadi maupun komersial, tanpa kewajiban",
        "mencantumkan atribusi, dan tidak boleh dijual kembali sebagai animasi.",
        "Atribusi di bawah dicantumkan atas kemauan sendiri, bukan karena",
        "diwajibkan lisensi.",
        "",
    ]
    for nama, slug, url, anim in catatan:
        baris += [
            f"### `{nama}.json`",
            "",
            f"- halaman : https://lottiefiles.com/free-animation/{slug}",
            f"- aset    : {url}",
            f"- ukuran  : {anim['w']}x{anim['h']} px, "
            f"{len(anim['layers'])} lapisan, {anim.get('fr')} fps",
            "",
        ]
    baris += [
        "## Pemutar",
        "",
        "`vendor/lottie_light.min.js` -- lottie-web 5.12.2 varian *light*,",
        f"diunduh dari {PEMUTAR_URL}",
        "([MIT License](https://github.com/airbnb/lottie-web/blob/master/LICENSE.md)).",
        "",
        "Disalin ke dalam proyek, bukan dipanggil dari CDN, supaya halaman login",
        "tetap jalan tanpa internet dan tampilannya tidak bisa berubah diam-diam",
        "saat CDN memperbarui versinya.",
        "",
    ]
    (LOTTIE_DIR / "SUMBER.md").write_text("\n".join(baris), encoding="utf-8")
    print(f"catatan  {(LOTTIE_DIR / 'SUMBER.md').name}")


if __name__ == "__main__":
    sys.exit(main())
