"""Halaman dashboard/beranda.

Isinya dua lapis:

1. Navigasi langkah harian (Hitung Kalori -> Rekomendasi Menu -> Rekomendasi
   Latihan). Langkah 2 & 3 terkunci sampai user menghitung kalori HARI ITU,
   dan otomatis terkunci lagi begitu tanggal berganti. Logika statusnya ada di
   core/progress.py -- di sini murni tampilannya.
2. Ringkasan data: tren berat badan, aktivitas terakhir, target kalori & makro
   hari ini, dan satu fakta kesehatan. Semua angkanya dibaca dari record yang
   tersimpan (bukan contoh/dummy), jadi kosong berarti user memang belum punya
   datanya.

Seluruh record milik user dimuat SEKALI di home_view lalu dioper ke tiap kartu,
supaya satu kali render tidak menembak database berkali-kali untuk data sama.
"""

from __future__ import annotations

import altair as alt
import html
import math
import pandas as pd
import streamlit as st

from datetime import date, datetime, timedelta

from src.nutrition import NutritionResult
from src.recommender import estimate_exercise_calories

from ..core.claims import claim_summary, set_meal_claim, set_workout_claim
from ..core.components import format_record_datetime, metric_card
from ..core.exercise_text import id_nama_latihan
from ..core.i18n import id_istilah, id_slot_makan
from ..core.icons import icon
from ..core.progress import (
    CALORIE,
    MEAL,
    WORKOUT,
    Step,
    build_steps,
    latest_per_day,
    load_user_records,
    parse_record_datetime,
)
from ..core.state import current_user


# Warna mark grafik: satu hue merek (lolos cek kontras >= 3:1 dan chroma di atas
# ambang pada latar putih). Track memakai langkah yang lebih muda dari hue yang
# sama supaya sisa/terisi tetap terbaca sebagai satu skala, bukan dua warna beda.
# Harus tetap sama dengan --green / --green-dark di core/styles.py. Duplikasi
# ini tidak bisa dihindari: Altair menerima warna sebagai nilai Python, bukan
# custom property CSS, jadi variabel tema tidak bisa dibaca dari sini.
ACCENT = "#FF4646"
ACCENT_DARK = "#D92A2A"
TRACK = "#fde8e8"
AXIS_LABEL = "#94a3b8"

RING_RADIUS = 52
RING_CIRCUMFERENCE = 2 * math.pi * RING_RADIUS

# Rentang grafik tren berat badan. None = seluruh riwayat.
TREND_RANGES: dict[str, int | None] = {
    "7 Hari Terakhir": 7,
    "30 Hari Terakhir": 30,
    "90 Hari Terakhir": 90,
    "Semua Waktu": None,
}

TREND_PERIOD_LABELS: dict[int | None, str] = {
    7: "minggu ini",
    30: "bulan ini",
    90: "3 bulan ini",
    None: "sejak awal",
}

# Vega tidak menerima locale dari Streamlit, jadi nama bulan dirakit sendiri
# lewat ekspresi label supaya sumbu tanggal tetap berbahasa Indonesia.
MONTH_SHORT = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
MONTH_LABEL_EXPR = (
    "date(datum.value) + ' ' + "
    "['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des'][month(datum.value)]"
)

HEALTH_FACTS = [
    "Minum air sebelum makan dapat membantu mengontrol nafsu makan dan mendukung hidrasi harian.",
    "Tidur 7-9 jam per malam membantu pemulihan otot dan menjaga hormon pengatur rasa lapar tetap stabil.",
    "Setengah piring berisi sayur dan buah adalah cara paling sederhana menjaga asupan serat harian.",
    "Jalan kaki 30 menit sehari sudah cukup untuk menurunkan risiko penyakit jantung.",
    "Protein yang cukup di setiap kali makan membantu rasa kenyang lebih lama.",
    "Latihan beban tidak hanya membentuk otot, tetapi juga menjaga kepadatan tulang.",
    "Makan perlahan memberi waktu bagi tubuh mengirim sinyal kenyang, sekitar 20 menit setelah mulai makan.",
    "Peregangan ringan setelah duduk lama membantu mengurangi kekakuan punggung dan leher.",
]

MAX_ACTIVITY_PREVIEW = 5
MAX_ACTIVITY_HISTORY = 30


def home_view(members: pd.DataFrame, foods: pd.DataFrame, exercises: pd.DataFrame) -> None:
    """Dashboard utama: header, kartu langkah harian, tren berat, aktivitas, dan ringkasan kalori."""
    user = current_user() or {}
    user_id = user.get("user_id")
    nutrition = st.session_state.nutrition

    records = load_user_records(user_id)
    steps = build_steps(records)
    summary = claim_summary(records, current_weight_kg())

    render_header(user)

    # User yang belum pernah menghitung kalori sama sekali dapat panel onboarding
    # (fokus ke satu aksi). User lama yang cuma belum menghitung HARI INI tetap
    # dapat kartu langkah biasa -- konteksnya beda: mereka sudah tahu alurnya.
    if not records[CALORIE]:
        render_onboarding(steps)
    else:
        render_step_banner(steps)
        render_step_cards(steps)

    render_summary(nutrition, records, summary)


def current_weight_kg() -> float | None:
    """Berat badan terakhir user, dipakai untuk menaksir kalori terbakar."""
    profile = st.session_state.get("profile") or {}
    try:
        return float(profile.get("weight_kg"))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Header & navigasi langkah
# --------------------------------------------------------------------------- #
def render_header(user: dict) -> None:
    """Sapaan nama pengguna beserta chip penanda role."""
    role_label = "Admin" if user.get("role") == "admin" else "Pengguna"
    st.markdown(
        f"""
        <div class="home-header">
            <div>
                <div class="home-title">Halo, {html.escape(str(user.get("name") or "Pengguna"))}</div>
                <div class="home-kicker">Berikut ringkasan aktivitas dan nutrisi Anda hari ini.</div>
            </div>
            <span class="chip">{html.escape(role_label)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_step_banner(steps: list[Step]) -> None:
    """Umpan balik sistem di atas kartu langkah: apresiasi kalau semua selesai,
    dorongan kalau baru sebagian, dan sapaan hari baru kalau semuanya reset."""
    done = sum(1 for step in steps if step.is_done)
    total = len(steps)

    if done == total:
        tone, name, message = (
            "success",
            "party",
            "Luar biasa! Kamu sudah menyelesaikan semua langkah hari ini. "
            "Tetap konsisten untuk hari esok yang lebih bugar &mdash; tubuh sehat "
            "adalah investasi terbaikmu!",
        )
    elif done == 0:
        tone, name, message = (
            "info",
            "sunrise",
            "Hari baru, semangat baru. Mulai dari <b>Langkah 1: Hitung Kalori</b> "
            "untuk membuka rekomendasi menu dan latihan hari ini.",
        )
    else:
        pending = [step.title for step in steps if not step.is_done]
        tone, name, message = (
            "progress",
            "flame",
            f"<b>{done} dari {total} langkah</b> selesai hari ini. Tinggal "
            f"{html.escape(' dan '.join(pending))} &mdash; sedikit lagi, kamu pasti bisa!",
        )

    st.markdown(
        f'<div class="step-banner is-{tone}">'
        f'<span class="step-banner-icon">{icon(name, size=22)}</span>'
        f'<span class="step-banner-text">{message}</span>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_step_cards(steps: list[Step]) -> None:
    """Tiga kartu langkah harian berdampingan, masing-masing dengan tombol aksinya."""
    columns = st.columns(3, gap="small")
    for column, step in zip(columns, steps):
        with column:
            with st.container(border=True, key=f"step_card_{step.number}"):
                st.markdown(step_card_html(step), unsafe_allow_html=True)
                render_step_button(step, key_prefix="step")


def step_card_html(step: Step) -> str:
    """Potongan HTML isi satu kartu langkah (nomor, ikon status, judul, keterangan)."""
    badge = "check" if step.is_done else ("lock" if step.is_locked else step.icon)
    state = "done" if step.is_done else ("locked" if step.is_locked else "open")
    return (
        '<div class="step-top">'
        f'<span class="step-kicker">LANGKAH {step.number}</span>'
        f'<span class="step-badge is-{state}">{icon(badge, size=20)}</span>'
        "</div>"
        f'<div class="step-title">{html.escape(step.title)}</div>'
        f'<div class="step-status is-{state}">{html.escape(step.status_label)}</div>'
    )


def render_step_button(step: Step, *, key_prefix: str, label: str | None = None) -> None:
    """Tombol aksi satu langkah: terkunci, ajakan mulai, atau tinjau ulang bila sudah selesai."""
    # Status ikut masuk ke key supaya kelas `st-key-...` yang dipakai CSS bisa
    # membedakan tombol selesai / terbuka / terkunci (lihat core/styles.py).
    key = f"{key_prefix}_action_{step.number}_{step.status}"
    if step.is_locked:
        st.button(
            "Terkunci",
            key=key,
            disabled=True,
            width="stretch",
            help="Selesaikan Langkah 1 (Hitung Kalori) hari ini untuk membuka fitur ini.",
        )
        return

    if st.button(
        label or step.action_label,
        key=key,
        type="secondary" if step.is_done else "primary",
        width="stretch",
    ):
        st.session_state.page = step.page
        st.rerun()


def render_onboarding(steps: list[Step]) -> None:
    """Panel pengenalan untuk pengguna yang belum pernah menghitung kalori sama sekali."""
    with st.container(border=True, key="onboard_panel"):
        st.markdown(
            '<div class="onboard-title">Mulai Perjalanan Sehat Anda</div>'
            '<div class="onboard-caption">Selesaikan perhitungan kalori Anda untuk '
            "membuka fitur rekomendasi makanan dan latihan.</div>",
            unsafe_allow_html=True,
        )
        columns = st.columns(3, gap="small")
        for column, step in zip(columns, steps):
            with column:
                with st.container(border=True, key=f"onboard_card_{step.number}"):
                    state = "locked" if step.is_locked else "open"
                    badge = "lock" if step.is_locked else step.icon
                    st.markdown(
                        f'<div class="onboard-card is-{state}">'
                        f'<span class="onboard-badge">{icon(badge, size=22)}</span>'
                        f'<div class="onboard-name">{html.escape(step.title)}</div>'
                        f'<div class="onboard-hint">{html.escape(step.hint if not step.is_locked else "Terkunci")}</div>'
                        "</div>",
                        unsafe_allow_html=True,
                    )
                    render_step_button(step, key_prefix="onboard")


# --------------------------------------------------------------------------- #
# Ringkasan data
# --------------------------------------------------------------------------- #
def render_summary(
    nutrition: NutritionResult | None,
    records: dict[str, list[dict]],
    summary: dict,
) -> None:
    """Susun dua baris kartu ringkasan: tren berat dan aktivitas, lalu kalori dan fakta kesehatan."""
    st.markdown('<div class="home-row-gap"></div>', unsafe_allow_html=True)
    trend_column, activity_column = st.columns([0.68, 0.32], gap="small")
    with trend_column:
        render_weight_trend_card(records[CALORIE], nutrition)
    with activity_column:
        render_activity_card(records, summary)

    st.markdown('<div class="home-row-gap"></div>', unsafe_allow_html=True)
    calorie_column, fact_column = st.columns([0.68, 0.32], gap="small")
    with calorie_column:
        render_calorie_card(nutrition, summary)
    with fact_column:
        render_fact_card()


def render_weight_trend_card(calorie_records: list[dict], nutrition: NutritionResult | None) -> None:
    """Kartu tren berat badan lengkap dengan pemilih rentang waktu dan grafiknya."""
    with st.container(border=True, key="card_trend"):
        title_column, range_column = st.columns([1, 0.42], vertical_alignment="top")
        with title_column:
            st.markdown('<div class="card-title">Tren Berat Badan</div>', unsafe_allow_html=True)
        with range_column:
            range_label = st.selectbox(
                "Rentang waktu",
                list(TREND_RANGES),
                index=1,
                key="trend_range",
                label_visibility="collapsed",
            )

        trend = weight_trend_data(calorie_records)
        if trend.empty:
            st.markdown(
                empty_state_html(
                    "hourglass",
                    "Belum ada data berat badan.",
                    "Selesaikan Hitung Kalori untuk mulai merekam tren.",
                ),
                unsafe_allow_html=True,
            )
            return

        window = TREND_RANGES[range_label]
        filtered = filter_trend(trend, window)
        if filtered.empty:
            st.markdown(
                empty_state_html(
                    "hourglass",
                    "Belum ada data pada rentang ini.",
                    "Pilih rentang yang lebih panjang untuk melihat riwayat Anda.",
                ),
                unsafe_allow_html=True,
            )
            return

        st.markdown(trend_summary_html(filtered, nutrition, window), unsafe_allow_html=True)
        st.altair_chart(weight_trend_chart(filtered), width="stretch")
        # Padanan tabel dari grafik: nilainya tetap terbaca tanpa mengandalkan
        # hover maupun persepsi warna.
        with st.expander("Lihat data"):
            table = filtered[["Label", "Berat (kg)"]].rename(columns={"Label": "Tanggal"})
            st.dataframe(table.iloc[::-1], hide_index=True, width="stretch")


def render_activity_card(records: dict[str, list[dict]], summary: dict) -> None:
    """Riwayat aktivitas yang bisa DIKLAIM, bukan sekadar dibaca.

    Sebelumnya kartu ini hanya menampilkan daftar kejadian. Sekarang isinya
    adalah daftar tugas hari ini: user mencentang menu yang benar-benar dimakan
    dan latihan yang benar-benar dikerjakan, dan kartu Target Kalori Harian di
    bawahnya langsung menyesuaikan diri. Riwayat hari-hari sebelumnya pindah ke
    dialog "Lihat Semua" -- di sana sifatnya memang hanya bacaan.
    """
    has_plan = bool(summary["meals_total"] or summary["workouts_total"])
    with st.container(border=True, key="card_activity"):
        st.markdown(card_head_html("Riwayat Aktivitas", "history"), unsafe_allow_html=True)

        if not has_plan:
            history = activity_items(records)
            if not history:
                st.markdown(
                    empty_state_html(
                        "hourglass",
                        "Belum ada aktivitas.",
                        "Mulai dari Hitung Kalori untuk mencatat aktivitas.",
                    ),
                    unsafe_allow_html=True,
                )
                return
            st.caption("Belum ada menu atau latihan untuk diklaim hari ini.")
            st.markdown(activity_list_html(history[:MAX_ACTIVITY_PREVIEW]), unsafe_allow_html=True)
            if st.button("Lihat Semua", key="activity_history", type="tertiary", width="stretch"):
                show_activity_history(records, summary)
            return

        st.markdown(claim_progress_html(summary), unsafe_allow_html=True)
        render_claim_list(records, summary, key_prefix="card", limit=MAX_ACTIVITY_PREVIEW)
        if st.button("Lihat Semua", key="activity_history", type="tertiary", width="stretch"):
            show_activity_history(records, summary)


def claim_progress_html(summary: dict) -> str:
    """Deretan chip ringkas: menu diklaim, latihan diklaim, dan perkiraan kalori terbakar."""
    return (
        '<div class="claim-progress">'
        f'<span class="chip">{summary["meals_claimed"]}/{summary["meals_total"]} menu</span>'
        f'<span class="chip">{summary["workouts_claimed"]}/{summary["workouts_total"]} latihan</span>'
        f'<span class="chip">~{summary["burned"]:,.0f} kkal terbakar</span>'
        "</div>"
    )


def render_claim_list(
    records: dict[str, list[dict]],
    summary: dict,
    *,
    key_prefix: str,
    limit: int | None = None,
    in_dialog: bool = False,
) -> None:
    """Daftar centang menu & latihan hari ini.

    `limit` adalah jatah baris untuk kartu dashboard yang sempit, dan sengaja
    DIBAGI antara dua kelompok, bukan dipakai berurutan. Satu menu harian berisi
    sembilan item, jadi pemotongan "lima teratas" akan selalu habis di menu dan
    latihan tidak pernah kelihatan -- padahal keduanya sama-sama perlu diklaim.
    Dialog memakai limit=None supaya semuanya bisa ditandai.

    Key checkbox memuat `key_prefix` karena item yang sama bisa tampil di kartu
    DAN di dialog sekaligus, dan Streamlit menolak dua widget dengan key identik.

    `records` dioper dari home_view, tidak dimuat ulang di sini -- seluruh
    halaman sengaja hanya membaca database satu kali per render.
    """
    user = current_user() or {}
    meal_items = [
        (slot, item) for slot, items in summary["meal_plan"].items() for item in items
    ]
    workout_items = list(summary["workout_plan"])
    meal_limit, workout_limit = _claim_preview_budget(limit, len(meal_items), len(workout_items))

    if meal_items:
        st.markdown('<div class="claim-group">Menu Hari Ini</div>', unsafe_allow_html=True)
        for slot, item in meal_items[:meal_limit]:
            identity = item.get("id") if item.get("id") is not None else item.get("name")
            label = (
                f"{id_slot_makan(slot)} · {item.get('name', '-')} "
                f"({safe_float(item.get('target_calories')):,.0f} kkal)"
            )
            claimed = st.checkbox(
                label,
                value=bool(item.get("is_eaten")),
                key=f"claim_meal_{key_prefix}_{slot}_{identity}",
            )
            if claimed != bool(item.get("is_eaten")):
                if set_meal_claim(user, records[MEAL], slot, identity, claimed):
                    invalidate_meal_session_state()
                    _rerun(in_dialog)

    if workout_items:
        st.markdown('<div class="claim-group">Latihan Hari Ini</div>', unsafe_allow_html=True)
        weight = current_weight_kg()
        for position, exercise in enumerate(workout_items[:workout_limit]):
            title = str(exercise.get("Title") or "-")
            burn = estimate_exercise_calories(exercise, weight)
            suffix = f" (~{burn:,.0f} kkal)" if burn else ""
            claimed = st.checkbox(
                f"{id_nama_latihan(title)}{suffix}",
                value=bool(exercise.get("is_done")),
                # Posisi ikut masuk ke key: dataset latihan memuat beberapa judul
                # kembar, dan dua checkbox dengan key sama membuat Streamlit
                # melempar DuplicateWidgetID dan seluruh dashboard gagal render.
                key=f"claim_workout_{key_prefix}_{position}_{title}",
            )
            if claimed != bool(exercise.get("is_done")):
                if set_workout_claim(user, records[WORKOUT], title, claimed):
                    invalidate_workout_session_state()
                    _rerun(in_dialog)

    hidden = (len(meal_items) - meal_limit) + (len(workout_items) - workout_limit)
    if hidden > 0:
        st.caption(f"{hidden} item lainnya — tekan **Lihat Semua** untuk menandainya.")


def _claim_preview_budget(limit: int | None, meals: int, workouts: int) -> tuple[int, int]:
    """Bagi jatah baris pratinjau antara menu dan latihan.

    Jatahnya dibagi kira-kira separuh-separuh, lalu sisa dari kelompok yang
    lebih pendek dikembalikan ke kelompok satunya. Jumlah baris yang ditampilkan
    tidak pernah melebihi `limit`.
    """
    if limit is None:
        return meals, workouts
    limit = max(limit, 0)
    if not meals:
        return 0, min(workouts, limit)
    if not workouts:
        return min(meals, limit), 0

    meal_share = min(meals, limit // 2 + limit % 2)
    workout_share = min(workouts, max(0, limit - meal_share))
    leftover = limit - meal_share - workout_share
    if leftover > 0:
        meal_share = min(meals, meal_share + leftover)
        workout_share = min(workouts, workout_share + (limit - meal_share - workout_share))
    return meal_share, workout_share


def _rerun(in_dialog: bool) -> None:
    """Jalankan ulang bagian yang tepat setelah sebuah klaim tersimpan.

    `st.rerun()` biasa menjalankan ulang SELURUH halaman, dan di dalam dialog
    itu berarti dialognya tertutup. Gejalanya persis seperti yang dilaporkan:
    mencentang satu item di "Lihat Semua" langsung melempar user keluar padahal
    masih ada item lain yang mau ditandai. `scope="fragment"` hanya menjalankan
    ulang isi dialognya, sehingga dialog tetap terbuka dan centangnya langsung
    terbarui.
    """
    st.rerun(scope="fragment" if in_dialog else "app")


def invalidate_meal_session_state() -> None:
    """Paksa halaman Rekomendasi Menu memuat ulang dari database.

    Klaim di dashboard menulis record baru; tanpa pembatalan ini halaman menu
    masih memegang salinan lama di session state dan centangnya akan terlihat
    berbeda dengan yang baru saja ditandai di sini.
    """
    st.session_state.food_recommendations = None
    st.session_state.meal_restored_on = None


def invalidate_workout_session_state() -> None:
    """Buang rekomendasi latihan di sesi agar dimuat ulang pada render berikutnya."""
    st.session_state.exercise_recommendations = None
    st.session_state.workout_restored_on = None


@st.dialog("Riwayat Aktivitas", width="large")
def show_activity_history(records: dict[str, list[dict]], summary: dict) -> None:
    """Dialog riwayat: tab klaim hari ini dan tab aktivitas lampau, datanya dimuat ulang tiap render."""
    # Argumen dialog TIDAK dievaluasi ulang saat isinya dijalankan ulang: ia
    # tetap memegang salinan dari saat tombol ditekan. Kalau dipakai apa adanya,
    # klaim pertama tersimpan ke database tetapi daftar di layar masih membaca
    # salinan lama -- centangnya balik lagi dan angkanya tidak bertambah, persis
    # gejala "item yang saya klaim tidak terhitung". Karena itu datanya dimuat
    # ulang di sini setiap kali dialog dirender.
    user = current_user() or {}
    records = load_user_records(user.get("user_id"))
    summary = claim_summary(records, current_weight_kg())

    claim_tab, history_tab = st.tabs(["Klaim Hari Ini", "Riwayat"])
    with claim_tab:
        if summary["meals_total"] or summary["workouts_total"]:
            st.markdown(claim_progress_html(summary), unsafe_allow_html=True)
            render_claim_list(records, summary, key_prefix="dialog", in_dialog=True)
        else:
            st.info(
                "Belum ada menu atau latihan hari ini. Buat Rekomendasi Menu dan "
                "Rekomendasi Latihan lebih dulu untuk bisa mengklaimnya di sini."
            )
    with history_tab:
        items = activity_items(records)
        if items:
            st.markdown(activity_list_html(items), unsafe_allow_html=True)
        else:
            st.info("Belum ada aktivitas yang tercatat.")


def render_calorie_card(nutrition: NutritionResult | None, summary: dict) -> None:
    """Kartu kalori harian: cincin konsumsi, sisa anggaran, dan batang tiap makronutrien."""
    consumed = summary["consumed"] if nutrition is not None else None
    burned = float(summary["burned"] or 0)
    with st.container(border=True, key="card_calorie"):
        title_column, menu_column = st.columns([1, 0.09], vertical_alignment="top")
        with title_column:
            # Angkanya ikut ditulis di keterangan, bukan cuma kalimat "sisa
            # kalori": cincin di bawah menampilkan yang SUDAH dimakan, jadi
            # tanpa angka ini keterangannya terbaca bertolak belakang dengan
            # angka besar di tengah cincin.
            if consumed is None:
                caption = "Selesaikan Hitung Kalori untuk melihat target harian"
            else:
                # Latihan yang sudah diklaim menambah anggaran hari itu: kalori
                # yang terbakar boleh "dibayar" kembali lewat makanan.
                budget = float(nutrition.target_calories or 0) + burned
                remaining = budget - consumed["calories"]
                caption = (
                    f"Sisa {remaining:,.0f} kkal yang dapat dikonsumsi hari ini"
                    if remaining >= 0
                    else f"Melebihi target sebanyak {abs(remaining):,.0f} kkal hari ini"
                )
                if burned:
                    caption += f" (termasuk ~{burned:,.0f} kkal dari latihan yang diklaim)"
            st.markdown(
                '<div class="card-title">Target Kalori Harian</div>'
                f'<div class="card-caption">{html.escape(caption)}</div>',
                unsafe_allow_html=True,
            )
        with menu_column:
            with st.popover("", icon=":material/more_vert:", help="Aksi cepat", key="calorie_menu"):
                if st.button("Buka Rekomendasi Menu", key="calorie_go_meal", width="stretch"):
                    st.session_state.page = "Meal Recommendation"
                    st.rerun()
                if st.button("Hitung Ulang Kalori", key="calorie_go_calc", width="stretch"):
                    st.session_state.page = "Calorie Calculator"
                    st.rerun()

        if nutrition is None:
            st.markdown(
                empty_state_html(
                    "target",
                    "Target harian belum tersedia.",
                    "Selesaikan Hitung Kalori untuk melihat target kalori dan makro.",
                ),
                unsafe_allow_html=True,
            )
            return

        # Cincin memakai ANGGARAN hari itu (target + kalori terbakar), bukan
        # target mentah. Sebelumnya latihan yang diklaim hanya disebut di
        # keterangan tetapi tidak menggeser angka mana pun, sehingga user yang
        # sudah berolahraga melihat cincinnya tidak bergerak sama sekali.
        target_calories = float(nutrition.target_calories or 0)
        budget_calories = target_calories + burned
        percent = progress_percent(consumed["calories"], budget_calories)

        ring_column, macro_column = st.columns([0.36, 0.64], vertical_alignment="center")
        with ring_column:
            st.markdown(
                calorie_ring_html(consumed["calories"], budget_calories, percent),
                unsafe_allow_html=True,
            )
            if burned:
                st.caption(
                    f"Anggaran naik dari {target_calories:,.0f} menjadi "
                    f"{budget_calories:,.0f} kkal karena ~{burned:,.0f} kkal terbakar."
                )
        with macro_column:
            st.markdown(
                "".join(
                    macro_row_html(label, consumed[key], getattr(nutrition, key))
                    for label, key in (
                        ("Karbohidrat", "carbohydrate_g"),
                        ("Protein", "protein_g"),
                        ("Lemak", "fat_g"),
                    )
                ),
                unsafe_allow_html=True,
            )


def render_fact_card() -> None:
    """Kartu fakta kesehatan harian yang bisa digeser ke fakta berikutnya."""
    # Fakta awal ditentukan tanggal supaya tiap hari beda tanpa perlu disimpan,
    # lalu bisa digeser manual lewat tombol.
    index = st.session_state.setdefault("health_fact_index", date.today().toordinal() % len(HEALTH_FACTS))
    with st.container(border=True, key="card_fact"):
        st.markdown(card_head_html("Fakta Kesehatan Hari Ini", "lightbulb"), unsafe_allow_html=True)
        st.markdown(
            f'<div class="fact-quote">&ldquo;{html.escape(HEALTH_FACTS[index % len(HEALTH_FACTS)])}&rdquo;</div>',
            unsafe_allow_html=True,
        )
        if st.button("Lihat Fakta Lainnya", key="fact_next", type="tertiary", width="stretch"):
            st.session_state.health_fact_index = (index + 1) % len(HEALTH_FACTS)
            st.rerun()


# --------------------------------------------------------------------------- #
# Potongan HTML
# --------------------------------------------------------------------------- #
def card_head_html(title: str, icon_name: str) -> str:
    """Potongan HTML kepala kartu: judul di kiri, ikon di kanan."""
    return (
        '<div class="card-head">'
        f'<div class="card-title">{html.escape(title)}</div>'
        f'<span class="card-head-icon">{icon(icon_name, size=20)}</span>'
        "</div>"
    )


def empty_state_html(icon_name: str, title: str, hint: str) -> str:
    """Potongan HTML keadaan kosong: ikon, judul, dan satu baris petunjuk."""
    return (
        '<div class="empty-state">'
        f'<span class="empty-icon">{icon(icon_name, size=30, stroke_width=1.5)}</span>'
        f'<div class="empty-title">{html.escape(title)}</div>'
        f'<div class="empty-hint">{html.escape(hint)}</div>'
        "</div>"
    )


def trend_summary_html(
    trend: pd.DataFrame,
    nutrition: NutritionResult | None,
    window: int | None,
) -> str:
    """Ringkasan di atas grafik tren: berat terakhir, target, dan selisih pada rentang terpilih."""
    latest = float(trend["Berat (kg)"].iloc[-1])
    first = float(trend["Berat (kg)"].iloc[0])
    delta = latest - first

    parts = [f'<span class="trend-value">{latest:.1f} kg</span>']
    if nutrition is not None and nutrition.ideal_weight:
        parts.append(
            f'<span class="trend-chip">Target: {float(nutrition.ideal_weight):.1f} kg</span>'
        )

    period = TREND_PERIOD_LABELS.get(window, "pada rentang ini")
    if len(trend) < 2 or abs(delta) < 0.05:
        parts.append(
            f'<span class="trend-delta is-flat">{icon("minus", size=16)}'
            f"Belum ada perubahan {html.escape(period)}</span>"
        )
    else:
        direction = "down" if delta < 0 else "up"
        arrow = "trending-down" if delta < 0 else "trending-up"
        parts.append(
            f'<span class="trend-delta is-{direction}">{icon(arrow, size=16)}'
            f"{delta:+.1f} kg {html.escape(period)}</span>"
        )

    return f'<div class="trend-summary">{"".join(parts)}</div>'


def activity_list_html(items: list[dict]) -> str:
    """Potongan HTML daftar aktivitas beserta ikon, judul, waktu, dan catatannya."""
    rows = []
    for item in items:
        subtitle = str(item.get("subtitle") or "")
        rows.append(
            '<div class="activity-row">'
            f'<span class="activity-icon">{icon(item["icon"], size=18)}</span>'
            '<span class="activity-body">'
            f'<span class="activity-name">{html.escape(str(item["title"]))}</span>'
            f'<span class="activity-time">{html.escape(str(item["time_label"]))}</span>'
            + (f'<span class="activity-note">{html.escape(subtitle)}</span>' if subtitle else "")
            + "</span></div>"
        )
    return f'<div class="activity-list">{"".join(rows)}</div>'


def calorie_ring_html(consumed: float, target: float, percent: int) -> str:
    """Potongan SVG cincin progres kalori beserta label angka di tengahnya."""
    filled = RING_CIRCUMFERENCE * min(max(percent, 0), 100) / 100
    remainder = max(RING_CIRCUMFERENCE - filled, 0.0)
    # Busur nilai sengaja tidak dirender saat 0%: stroke-linecap "round" pada
    # panjang 0 tetap menggambar titik kecil yang terbaca seolah ada progres.
    value_arc = (
        f'<circle class="ring-value" cx="60" cy="60" r="{RING_RADIUS}" '
        f'stroke-dasharray="{filled:.2f} {remainder:.2f}" transform="rotate(-90 60 60)"/>'
        if filled > 0
        else ""
    )
    # Format angka mengikuti konvensi yang sudah dipakai view lain (calorie.py,
    # admin.py) supaya satu aplikasi tidak memakai dua gaya pemisah ribuan.
    label = f"{consumed:,.0f} dari {target:,.0f} kkal ({percent}%)"
    return (
        '<div class="ring-wrap">'
        f'<svg class="ring-svg" viewBox="0 0 120 120" role="img" aria-label="{html.escape(label)}">'
        f'<circle class="ring-track" cx="60" cy="60" r="{RING_RADIUS}"/>{value_arc}'
        "</svg>"
        '<div class="ring-label">'
        f'<div class="ring-number">{consumed:,.0f}</div>'
        f'<div class="ring-caption">/ {target:,.0f} kkal</div>'
        "</div></div>"
    )


def macro_row_html(label: str, current: float, target: float) -> str:
    """Potongan HTML satu baris makronutrien: nama, angka, dan batang progresnya."""
    percent = progress_percent(current, target)
    return (
        '<div class="macro-row">'
        '<div class="macro-meta">'
        f'<span class="macro-name"><i class="macro-dot"></i>{html.escape(label)}</span>'
        f"<span>{current:,.0f} / {target:,.0f}g</span>"
        "</div>"
        '<div class="progress-track">'
        f'<div class="progress-fill" style="width:{percent}%"></div>'
        "</div></div>"
    )


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def weight_trend_data(calorie_records: list[dict]) -> pd.DataFrame:
    """Susun tabel tanggal dan berat badan dari riwayat kalori, satu titik per tanggal."""
    rows = []
    for record in calorie_records:
        profile = record.get("profile") or {}
        timestamp = parse_record_datetime(record.get("created_at"))
        weight = profile.get("weight_kg")
        if timestamp is None or weight is None:
            continue
        try:
            weight_value = float(weight)
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "Tanggal": timestamp,
                "Berat (kg)": round(weight_value, 1),
                "Label": format_date_id(timestamp),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["Tanggal", "Berat (kg)", "Label"])

    # Satu titik per TANGGAL, ambil penimbangan terakhir hari itu. Tiap
    # "Hitung Ulang" menulis record baru, jadi satu hari bisa punya beberapa
    # record; tanpa ini grafik menumpuk beberapa titik di absis yang hampir
    # sama (garisnya jadi patah vertikal) dan selisih berat salah baca koreksi
    # ketik dalam sehari sebagai perubahan sebulan.
    frame = pd.DataFrame(rows).sort_values("Tanggal")
    frame["Tanggal"] = frame["Tanggal"].dt.normalize()
    frame = frame.drop_duplicates(subset="Tanggal", keep="last")
    return frame.reset_index(drop=True)


def filter_trend(trend: pd.DataFrame, window: int | None) -> pd.DataFrame:
    """Batasi tabel tren ke rentang hari terakhir; None berarti seluruh riwayat."""
    if window is None or trend.empty:
        return trend
    cutoff = datetime.now() - timedelta(days=window)
    return trend[trend["Tanggal"] >= cutoff].reset_index(drop=True)


def weight_trend_chart(trend: pd.DataFrame) -> alt.LayerChart:
    """Bangun grafik garis Altair untuk tren berat, lengkap dengan titik dan tooltip hover."""
    hover = alt.selection_point(
        fields=["Tanggal"],
        nearest=True,
        on="pointerover",
        clear="pointerout",
        empty=False,
    )

    # Encoding sumbu X dipakai ULANG oleh semua layer. Kalau tiap layer punya
    # definisi axis yang berbeda (mis. layer penangkap hover memakai axis=None),
    # Vega-Lite menganggapnya konflik saat menggabungkan layer dan justru
    # menghapus sumbunya -- label tanggalnya hilang sama sekali.
    x_encoding = alt.X(
        "Tanggal:T",
        title=None,
        axis=alt.Axis(
            grid=False,
            domain=False,
            ticks=False,
            labelPadding=10,
            labelColor=AXIS_LABEL,
            labelFontSize=11,
            tickCount=4,
            labelExpr=MONTH_LABEL_EXPR,
        ),
    )

    base = alt.Chart(trend).encode(
        x=x_encoding,
        # stack=None WAJIB: Vega-Lite otomatis men-stack mark area, dan saat
        # stacking aktif domain sumbu Y dipaksa mulai dari 0 sehingga
        # scale(zero=False) diabaikan -- grafiknya jadi garis rata di ujung atas
        # karena rentang berat (mis. 68-71 kg) tenggelam di skala 0-71.
        y=alt.Y(
            "Berat (kg):Q",
            title=None,
            axis=None,
            stack=None,
            scale=alt.Scale(zero=False, nice=True),
        ),
    )

    area = base.mark_area(
        interpolate="monotone",
        line={"color": ACCENT, "strokeWidth": 2, "strokeCap": "round", "strokeJoin": "round"},
        color=alt.Gradient(
            gradient="linear",
            x1=1, x2=1, y1=1, y2=0,
            stops=[
                alt.GradientStop(color="#ffffff", offset=0),
                alt.GradientStop(color=ACCENT, offset=1),
            ],
        ),
        # fillOpacity, bukan opacity: `opacity` ikut meredupkan garis di atas
        # area sehingga garis trennya jadi pucat.
        fillOpacity=0.18,
    )

    tooltip = [
        alt.Tooltip("Label:N", title="Tanggal"),
        alt.Tooltip("Berat (kg):Q", title="Berat", format=".1f"),
    ]
    # Lapisan penangkap hover sengaja dipisah dan transparan: area hit-nya lebar
    # (mudah dikenai kursor) tanpa ikut menggambar titik di grafik.
    selectors = (
        alt.Chart(trend)
        .mark_point(size=600)
        .encode(x=x_encoding, opacity=alt.value(0), tooltip=tooltip)
        .add_params(hover)
    )
    rule = (
        alt.Chart(trend)
        .mark_rule(color="#cbd5e1", strokeWidth=1)
        .encode(x=x_encoding)
        .transform_filter(hover)
    )
    dots = base.mark_point(size=90, filled=True, color=ACCENT, stroke="#ffffff", strokeWidth=2).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
    )

    layers = [area, rule, selectors, dots]
    if len(trend) < 3:
        # Satu-dua titik tidak membentuk garis yang terbaca; tandai titiknya.
        layers.append(
            base.mark_point(size=90, filled=True, color=ACCENT, stroke="#ffffff", strokeWidth=2)
        )

    # Tinggi 230 sudah termasuk pita label tanggal di bawah plot (kartunya
    # memakai min-height, bukan height, jadi labelnya tidak pernah terpotong).
    return alt.layer(*layers).properties(height=230).configure_view(strokeWidth=0)


def activity_items(records: dict[str, list[dict]]) -> list[dict]:
    """Feed aktivitas gabungan dari ketiga fitur, terbaru di atas."""
    items: list[dict] = []

    for record in latest_per_day(records.get(WORKOUT, [])):
        created_at = parse_record_datetime(record.get("created_at"))
        exercises = record.get("recommendations") or []
        if not isinstance(exercises, list):
            continue
        for exercise in exercises[:4]:
            if not isinstance(exercise, dict):
                continue
            body_part = id_istilah(exercise.get("BodyPart"))
            equipment = id_istilah(exercise.get("Equipment"))
            items.append(
                {
                    "icon": "dumbbell",
                    "title": f"Latihan {body_part} ({equipment})",
                    "subtitle": str(exercise.get("Title") or ""),
                    "created_at": created_at,
                }
            )

    for record in latest_per_day(records.get(MEAL, [])):
        created_at = parse_record_datetime(record.get("created_at"))
        eaten = eaten_by_slot(record)
        if eaten:
            for slot, names in eaten.items():
                items.append(
                    {
                        "icon": "utensils",
                        "title": id_slot_makan(slot),
                        "subtitle": ", ".join(names),
                        "created_at": created_at,
                    }
                )
        else:
            items.append(
                {
                    "icon": "utensils",
                    "title": "Rekomendasi Menu dibuat",
                    "subtitle": "Belum ada menu yang ditandai sudah dimakan",
                    "created_at": created_at,
                }
            )

    for record in latest_per_day(records.get(CALORIE, [])):
        created_at = parse_record_datetime(record.get("created_at"))
        nutrition = record.get("nutrition") or {}
        status = str(nutrition.get("bmi_status") or "").strip()
        items.append(
            {
                "icon": "calculator",
                "title": f"Hitung Kalori - {status}" if status else "Hitung Kalori",
                "subtitle": (
                    f"Target {safe_float(nutrition.get('target_calories')):,.0f} kkal"
                    if nutrition.get("target_calories")
                    else ""
                ),
                "created_at": created_at,
            }
        )

    items.sort(key=lambda item: item["created_at"] or datetime.min, reverse=True)
    for item in items:
        item["time_label"] = relative_time_label(item["created_at"])
    return items[:MAX_ACTIVITY_HISTORY]


def eaten_by_slot(record: dict) -> dict[str, list[str]]:
    """Nama menu yang sudah dicentang 'sudah dimakan', dikelompokkan per slot."""
    result: dict[str, list[str]] = {}
    recommendations = record.get("recommendations") or {}
    if not isinstance(recommendations, dict):
        return result
    for slot, items in recommendations.items():
        names = [
            str(item.get("name"))
            for item in (items or [])
            if isinstance(item, dict) and item.get("is_eaten") and item.get("name")
        ]
        if names:
            result[slot] = names
    return result


# Perhitungan konsumsi harian pindah ke core/claims.py (consumed_nutrition)
# karena dashboard kini tidak hanya MEMBACA statusnya tapi juga MENULISNYA
# lewat klaim, dan kedua sisi harus memakai aturan resolusi yang sama.


# --------------------------------------------------------------------------- #
# Helper kecil
# --------------------------------------------------------------------------- #
def safe_float(value) -> float:
    """Ubah nilai jadi float; balas 0.0 bila kosong atau tidak bisa dikonversi."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def progress_percent(current: float, target: float) -> int:
    """Persentase pencapaian target, dipotong pada rentang 0-100."""
    if not target:
        return 0
    return round(max(0.0, min(current / target, 1.0)) * 100)


def format_date_id(value: datetime) -> str:
    """Format tanggal gaya Indonesia, misalnya 5 Mar 2026."""
    return f"{value.day} {MONTH_SHORT[value.month - 1]} {value.year}"


def relative_time_label(value: datetime | None) -> str:
    """Label waktu relatif (baru saja, 5 menit yang lalu); lebih dari sepekan pakai tanggal penuh."""
    if value is None:
        return "Belum ada"

    total_seconds = int((datetime.now() - value).total_seconds())
    if total_seconds < 0:
        return format_record_datetime(value)
    if total_seconds < 60:
        return "Baru saja"

    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes} menit yang lalu"

    hours = minutes // 60
    if hours < 24:
        return f"{hours} jam yang lalu"

    days = hours // 24
    if days < 7:
        return f"{days} hari yang lalu"

    return format_record_datetime(value)


def show_compact_targets(nutrition) -> None:
    """Empat kartu metrik ringkas: target kalori, karbohidrat, protein, dan lemak."""
    cols = st.columns(4)
    for col, (label, value) in zip(
        cols,
        [
            ("Target Kalori", f"{nutrition.target_calories:,.0f} kkal"),
            ("Karbohidrat", f"{nutrition.carbohydrate_g:,.0f} g"),
            ("Protein", f"{nutrition.protein_g:,.0f} g"),
            ("Lemak", f"{nutrition.fat_g:,.0f} g"),
        ],
    ):
        with col:
            metric_card(label, value)
