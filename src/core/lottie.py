"""Pemuat animasi Lottie dari berkas aset lokal, dengan cache."""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from src.paths import ASSETS_DIR


LOTTIE_DIR = ASSETS_DIR / "lottie"
PEMUTAR_PATH = ASSETS_DIR / "vendor" / "lottie_light.min.js"


@st.cache_data(show_spinner=False)
def _baca_berkas(path_teks: str) -> str:
    """Baca satu berkas aset Lottie dari folder assets; balas None bila tidak ada."""
    try:
        return Path(path_teks).read_text(encoding="utf-8")
    except OSError:
        return ""


def lottie_tersedia(nama: str) -> bool:
    """True kalau animasi DAN pemutarnya sama-sama ada."""
    return bool(
        _baca_berkas(str(LOTTIE_DIR / f"{nama}.json"))
        and _baca_berkas(str(PEMUTAR_PATH))
    )


def _aman_untuk_script(json_teks: str) -> str:
    """Cegah isi JSON menutup tag <script> yang membungkusnya.

    Satu-satunya rangkaian yang bisa mengakhiri <script> lebih awal adalah
    "</script". Menggantikan setiap "</" dengan "<\\/" menutup celah itu dan
    tetap aman: "<" pada JSON hanya pernah muncul di dalam string, dan "\\/"
    adalah escape yang sah untuk "/" -- jadi JSON.parse mengembalikannya utuh.
    """
    return json_teks.replace("</", "<\\/")


_TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; background: transparent; overflow: hidden; }}
  #panggung {{ width: 100%; height: 100vh; }}
  /* Streamlit tidak mewarisi warna latar halaman ke dalam iframe komponen,
     jadi latar dibiarkan transparan di sini dan diserahkan ke halaman induk. */
  #panggung svg {{ display: block; width: 100%; height: 100%; }}
</style>
<div id="panggung"></div>
<script>{pemutar}</script>
<script type="application/json" id="data-animasi">{data}</script>
<script>
(function () {{
  var panggung = document.getElementById("panggung");
  var simpul = document.getElementById("data-animasi");
  if (!panggung || !simpul || typeof lottie === "undefined") {{ return; }}

  var animasi;
  try {{
    animasi = lottie.loadAnimation({{
      container: panggung,
      renderer: "svg",
      loop: {loop},
      autoplay: true,
      animationData: JSON.parse(simpul.textContent),
      rendererSettings: {{ preserveAspectRatio: "xMidYMid meet" }}
    }});
  }} catch (e) {{
    // Animasi rusak tidak boleh menjatuhkan apa pun; kotaknya cukup kosong.
    return;
  }}

  // Hormati setelan sistem "kurangi animasi": tampilkan satu bingkai diam
  // daripada gerakan berulang yang bisa memicu ketidaknyamanan.
  var diam = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
  if (diam && diam.matches) {{
    animasi.addEventListener("DOMLoaded", function () {{ animasi.goToAndStop(0, true); }});
  }}
}})();
</script>
"""


def render_lottie(nama: str, *, height: int = 420, loop: bool = True) -> bool:
    """Tampilkan animasi `assets/lottie/<nama>.json`.

    Mengembalikan True kalau animasinya benar-benar dirender, supaya pemanggil
    bisa menyiapkan tampilan pengganti saat asetnya belum ada.
    """
    data = _baca_berkas(str(LOTTIE_DIR / f"{nama}.json"))
    pemutar = _baca_berkas(str(PEMUTAR_PATH))
    if not data or not pemutar:
        return False

    dokumen = _TEMPLATE.format(
        pemutar=pemutar,
        data=_aman_untuk_script(data),
        loop="true" if loop else "false",
    )

    # st.iframe menggantikan st.components.v1.html, yang sudah ditandai usang
    # ("will be removed after 2026-06-01"). Yang lama tetap disiapkan sebagai
    # cadangan karena requirements.txt hanya menuntut streamlit>=1.61.0,
    # sedangkan st.iframe belum tentu ada di setiap rilis 1.61.x.
    if hasattr(st, "iframe"):
        st.iframe(dokumen, height=height)
    else:
        components.html(dokumen, height=height, scrolling=False)
    return True
