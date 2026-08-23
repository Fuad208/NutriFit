"""Halaman rekomendasi latihan & tutorial video."""

from __future__ import annotations

import html
import pandas as pd
import re
import streamlit as st

from datetime import date
from difflib import SequenceMatcher

from src.database import WORKOUT_STORE
from src.recommender import (
    MAX_EXERCISE_COUNT,
    MIN_EXERCISE_COUNT,
    NEEDS_SUPERVISION_COLUMN,
    TARGET_MUSCLE_GROUPS,
    default_exercise_count,
    recommend_exercises,
    switch_exercise,
)

from ..core.data import TRAINING_DETAIL_DIR, load_training_tutorials
from ..core.exercise_text import (
    id_deskripsi_latihan,
    id_inti_latihan,
    id_langkah_latihan,
    id_nama_latihan,
    lexicon_is_available,
)
from ..core.i18n import id_daftar, id_istilah, id_tujuan
from ..core.progress import latest_record_today
from ..core.state import current_user, ensure_nutrition_ready, persist_workout_recommendation


def normalize_exercise_name(value: str) -> str:
    """Seragamkan nama latihan untuk pencocokan: huruf kecil, tanpa simbol, tanpa prefiks katalog."""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()
    removable_prefixes = ("fyr ", "fyr2 ", "am ")
    for prefix in removable_prefixes:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return re.sub(r"\s+", " ", normalized)


def exercise_name_tokens(value: str) -> set[str]:
    """Kumpulan kata penting dari nama latihan, kata sambung umum dibuang."""
    ignored = {"and", "the", "a", "an", "with", "to", "on", "of"}
    return {token for token in normalize_exercise_name(value).split() if token and token not in ignored}


def find_training_tutorial(exercise: dict, tutorials: list[dict]) -> dict | None:
    """Cari tutorial paling mirip dengan satu latihan; None bila skor kemiripannya di bawah ambang."""
    if not tutorials:
        return None

    title = normalize_exercise_name(exercise.get("Title", ""))
    title_tokens = exercise_name_tokens(exercise.get("Title", ""))
    body_part = normalize_exercise_name(exercise.get("BodyPart", ""))
    equipment = normalize_exercise_name(exercise.get("Equipment", ""))

    best_tutorial = None
    best_score = 0.0
    for tutorial in tutorials:
        name = normalize_exercise_name(tutorial.get("name", ""))
        if not name:
            continue

        name_tokens = exercise_name_tokens(tutorial.get("name", ""))
        shared_tokens = title_tokens & name_tokens
        title_match = bool(title and (title in name or name in title))
        if not shared_tokens and not title_match:
            continue

        token_union = title_tokens | name_tokens
        token_overlap = len(shared_tokens) / len(token_union) if token_union else 0
        score = (SequenceMatcher(None, title, name).ratio() * 0.65) + (token_overlap * 0.35)
        if title_match:
            score += 0.2
        if body_part and body_part in normalize_exercise_name(tutorial.get("body_part", "")):
            score += 0.08
        if equipment and equipment in normalize_exercise_name(tutorial.get("equipment", "")):
            score += 0.08

        if score > best_score:
            best_score = score
            best_tutorial = tutorial

    return best_tutorial if best_score >= 0.62 else None


def tutorial_has_video(tutorial: dict | None) -> bool:
    """True bila berkas animasi tutorial benar-benar ada di folder dataProgramTraining."""
    if not tutorial:
        return False
    gif_path = TRAINING_DETAIL_DIR / str(tutorial.get("gif_url", ""))
    return gif_path.exists()


@st.cache_data(show_spinner=False)
def exercises_with_video_tutorials(exercises: pd.DataFrame, tutorials: list[dict]) -> pd.DataFrame:
    """Saring dataset latihan, sisakan yang punya berkas tutorial video; hasilnya di-cache."""
    if exercises.empty or not tutorials:
        return exercises.iloc[0:0].copy()

    eligible_indices = []
    for index, row in exercises.iterrows():
        tutorial = find_training_tutorial(row.to_dict(), tutorials)
        if tutorial_has_video(tutorial):
            eligible_indices.append(index)

    return exercises.loc[eligible_indices].copy()


def recommendations_have_video_tutorials(recommendations: pd.DataFrame | None, tutorials: list[dict]) -> bool:
    """True bila seluruh latihan pada rekomendasi sudah punya tutorial video."""
    if recommendations is None or recommendations.empty:
        return False
    return all(tutorial_has_video(find_training_tutorial(row.to_dict(), tutorials)) for _, row in recommendations.iterrows())


def supervision_chip(row) -> str:
    """Penanda pada kartu untuk latihan yang diambil dari level di atas level pengguna."""
    if not bool(row.get(NEEDS_SUPERVISION_COLUMN, False)):
        return ""
    return '<span class="chip chip-warning">Perlu pendampingan</span>'


def workout_view(exercises: pd.DataFrame) -> None:
    """Halaman rekomendasi latihan: filter target otot, hasilkan program, simpan, dan tampilkan kartunya."""
    st.markdown('<div class="brand">Rekomendasi Latihan Gym</div>', unsafe_allow_html=True)
    st.caption("Pilih target otot dan dapatkan program latihan terstruktur yang disesuaikan dengan tujuan Anda.")

    if not ensure_nutrition_ready():
        return

    profile = st.session_state.profile
    tutorials = load_training_tutorials()
    recommendation_exercises = exercises_with_video_tutorials(exercises, tutorials)
    if recommendation_exercises.empty:
        st.warning("Belum ada data latihan dengan tutorial video yang bisa direkomendasikan.")
        return

    body_parts = list(TARGET_MUSCLE_GROUPS)

    # Formulirnya tinggal DUA isian. Jenis latihan ditentukan tujuan kebugaran dan
    # alat ditentukan level pengalaman; keduanya bukan masukan pengguna.
    # Lihat docs/catatan-desain.md bagian 10.
    cols = st.columns(2)
    with cols[0]:
        body_part = st.selectbox("Target Otot", body_parts, index=body_parts.index("Dada"))
    # Nilai bawaannya ditentukan sistem dari level pengalaman dan tingkat
    # aktivitas, bukan dipatok 5 untuk semua orang. Tetap bisa digeser: berapa
    # lama waktu pengguna hari ini adalah hal yang tidak diketahui sistem.
    jumlah_bawaan = default_exercise_count(
        profile["experience_level"], profile.get("activity_level", "Medium")
    )
    with cols[1]:
        limit = st.number_input(
            "Jumlah Latihan",
            min_value=MIN_EXERCISE_COUNT,
            max_value=MAX_EXERCISE_COUNT,
            value=jumlah_bawaan,
            step=1,
            help=(
                f"Sistem menyarankan {jumlah_bawaan} latihan untuk level "
                f"{id_istilah(profile['experience_level'])} dengan aktivitas "
                f"{id_istilah(profile.get('activity_level', 'Medium'))}. "
                f"Sesuaikan bila waktu Anda hari ini berbeda "
                f"({MIN_EXERCISE_COUNT}-{MAX_EXERCISE_COUNT})."
            ),
        )

    st.caption(
        f"Jenis latihan disesuaikan dengan tujuan Anda ({id_tujuan(profile['fitness_goal'])}), "
        f"pilihan alat dengan level {id_istilah(profile['experience_level'])}, "
        f"dan jumlahnya disarankan {jumlah_bawaan} latihan."
    )

    workout_filters = {
        "body_part": body_part,
        "experience_level": profile["experience_level"],
        "fitness_goal": profile["fitness_goal"],
        "limit": limit,
    }
    generate = st.button("Buat Program Latihan", use_container_width=True)

    if generate:
        st.session_state.excluded_exercise_titles = []
        st.session_state.workout_filters = workout_filters
        st.session_state.exercise_recommendations = recommend_exercises(
            recommendation_exercises,
            body_part=workout_filters["body_part"],
            experience_level=workout_filters["experience_level"],
            fitness_goal=workout_filters["fitness_goal"],
            limit=workout_filters["limit"],
        )
        st.session_state.workout_from_storage = False
        persist_workout_recommendation(
            st.session_state.exercise_recommendations,
            workout_filters,
        )
    else:
        restore_today_workout()

    # Program hanya disusun setelah tombolnya ditekan, supaya pengguna tidak
    # rekomendasi ikut dibuat otomatis saat halaman dibuka (lewat pengecekan
    # needs_video_refresh), sehingga user mengira daftar itu hasil pilihannya
    # padahal filternya belum pernah dia tekan.
    if st.session_state.exercise_recommendations is None:
        st.info(
            "Atur target otot, jenis latihan, alat, dan jumlah latihan di atas, "
            "lalu tekan **Buat Program Latihan** untuk melihat rekomendasinya."
        )
        return

    if st.session_state.get("workout_from_storage"):
        st.caption(
            "Menampilkan program latihan yang sudah Anda buat hari ini. "
            "Tekan **Buat Program Latihan** kalau ingin menyusun ulang."
        )

    display_workouts(
        recommendation_exercises,
        st.session_state.exercise_recommendations,
        tutorials,
        st.session_state.workout_filters or workout_filters,
    )


def restore_today_workout() -> None:
    """Muat kembali program latihan HARI INI dari database ke session state."""
    if st.session_state.exercise_recommendations is not None:
        return

    today = date.today().isoformat()
    if st.session_state.get("workout_restored_on") == today:
        return
    st.session_state.workout_restored_on = today

    record = latest_record_today(WORKOUT_STORE, current_user().get("user_id"))
    rows = (record or {}).get("recommendations")
    if not isinstance(rows, list) or not rows:
        return

    # Disimpan sebagai list dict (to_dict("records")), sedangkan seluruh
    # tampilan & fitur "Ganti" bekerja di atas DataFrame.
    st.session_state.exercise_recommendations = pd.DataFrame(rows)
    st.session_state.excluded_exercise_titles = []
    st.session_state.workout_from_storage = True

    filters = record.get("filters")
    if isinstance(filters, dict) and filters:
        st.session_state.workout_filters = filters


def display_workouts(
    exercises: pd.DataFrame,
    recommendations: pd.DataFrame | None,
    tutorials: list[dict],
    active_filters: dict,
) -> None:
    """Render daftar kartu latihan beserta tombol ganti latihan dan buka tutorial."""
    if recommendations is None or recommendations.empty:
        st.info("Belum ada rekomendasi latihan yang cocok dengan filter Anda.")
        return

    body_part = active_filters.get("body_part") or recommendations.iloc[0]["BodyPart"]
    st.markdown(
        f"""
        <div class="workout-program">
            <div class="workout-program-title">Program Latihan ({html.escape(str(body_part))})</div>
            <p class="subtle">Gerakan dipilih berdasarkan target otot, level pengalaman, dan variasi alat.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    rows = list(recommendations.iterrows())
    for start in range(0, len(rows), 3):
        cols = st.columns(3)
        for offset, col in enumerate(cols):
            item_index = start + offset
            if item_index >= len(rows):
                continue
            number = item_index + 1
            _, row = rows[item_index]
            with col:
                exercise = row.to_dict()
                tutorial = find_training_tutorial(exercise, tutorials)
                exercise_key = exercise.get("Program_ID", row.get("Title", number))
        # height="stretch" pada kartu membuat seluruh kartu dalam satu baris
        # bertinggi sama, sehingga tombolnya sejajar walau panjang judulnya berbeda.
                with st.container(border=True, height="stretch", key=f"kartu_latihan_{number}"):
                    with st.container(height="stretch"):
                        header_cols = st.columns([0.3, 0.7], vertical_alignment="top")
                        with header_cols[0]:
                            st.markdown(f'<div class="workout-number">{number}</div>', unsafe_allow_html=True)
                        with header_cols[1]:
                            # horizontal_alignment: tombol menempel ke tepi
                            # kanan tanpa perlu melebar sepenuh kolom -- kalau
                            # dilebarkan, labelnya pecah jadi dua baris.
                            with st.container(horizontal_alignment="right"):
                                ganti = st.button(
                                    "Ganti Latihan",
                                    key=f"workout_switch_{number}_{exercise_key}",
                                )
                        if ganti:
                            filters = dict(active_filters or st.session_state.workout_filters or {})
                            filters["excluded_titles"] = st.session_state.excluded_exercise_titles
                            replacement = switch_exercise(exercises, exercise, recommendations, filters)
                            if replacement:
                                st.session_state.excluded_exercise_titles.append(str(row["Title"]))
                                st.session_state.workout_filters = active_filters
                                updated = recommendations.copy()
                                target_index = recommendations.index[item_index]
                                for key, value in replacement.items():
                                    updated.loc[target_index, key] = value
                                st.session_state.exercise_recommendations = updated
                                persist_workout_recommendation(updated, active_filters or filters)
                                st.rerun()
                            st.warning("Belum ada latihan pengganti yang relevan.")

                        # Urutan sengaja: nama -> takaran -> chip -> inti
                        # gerakan. Takaran (set/repetisi/istirahat) naik ke
                        # bawah judul karena itu yang dibaca berulang kali saat
                        # latihan berjalan, sedangkan chip dan keterangan hanya
                        # dibaca sekali waktu memilih program.
                        st.markdown(
                            f"""
                            <div class="exercise-head">
                                <div class="exercise-title">{html.escape(id_nama_latihan(row['Title']))}</div>
                                <div class="workout-dose">{row['sets']} set x {row['reps']} repetisi <span class="workout-dose-sep">|</span> Istirahat {row['rest_seconds']} detik</div>
                            </div>
                            <div class="chip-row">
                                <span class="chip">{html.escape(id_istilah(row['BodyPart']))}</span>
                                <span class="chip">{html.escape(id_istilah(row['Equipment']))}</span>
                                <span class="chip">{html.escape(id_istilah(row['Level']))}</span>
                                {supervision_chip(row)}
                            </div>
                            <div class="exercise-desc">{html.escape(id_inti_latihan(exercise, tutorial))}</div>
                            """,
                            unsafe_allow_html=True,
                        )

                    # DI LUAR container "stretch" di atas: itulah yang menahannya
                    # tetap rata di dasar kartu, sejajar di ketiga kartu sebaris,
                    # berapa pun panjang nama latihannya.
                    if st.button("Lihat Panduan", key=f"workout_detail_{number}_{exercise_key}", use_container_width=True):
                        st.session_state.selected_workout = {
                            "exercise": exercise,
                            "tutorial": tutorial,
                        }
                        st.session_state.page = "Workout Tutorial"
                        st.rerun()
        st.markdown('<div class="workout-card-row"></div>', unsafe_allow_html=True)


def workout_tutorial_view() -> None:
    """Halaman tutorial satu latihan: animasi gerakan, langkah pelaksanaan, dan keterangannya."""
    selected = st.session_state.get("selected_workout")
    if not selected:
        st.warning("Pilih latihan dari halaman rekomendasi terlebih dahulu.")
        if st.button("Kembali ke Rekomendasi Latihan", use_container_width=True):
            st.session_state.page = "Workout Recommendation"
            st.rerun()
        return

    exercise = selected.get("exercise") or {}
    tutorial = selected.get("tutorial")

    if st.button("Kembali", use_container_width=False):
        st.session_state.page = "Workout Recommendation"
        st.rerun()

    st.markdown('<div class="brand">Tutorial Latihan</div>', unsafe_allow_html=True)

    # .title() dilepas: kapitalisasi kini ditangani id_nama_latihan, yang tidak
    # merusak singkatan seperti "FYR2" dan "MetaBurn".
    title = str(tutorial.get("name") if tutorial else exercise.get("Title", "Latihan"))
    st.markdown(
        f'<div class="section-title">{html.escape(id_nama_latihan(title))}</div>',
        unsafe_allow_html=True,
    )
    st.write(id_deskripsi_latihan(exercise, tutorial))

    if not tutorial:
        st.info("Detail tutorial belum ditemukan untuk latihan ini.")
        render_original_description(exercise)
        return

    gif_path = TRAINING_DETAIL_DIR / str(tutorial.get("gif_url", ""))
    image_path = TRAINING_DETAIL_DIR / str(tutorial.get("image", ""))
    media_path = gif_path if gif_path.exists() else image_path

    media_col, detail_col = st.columns([1, 1.4])
    with media_col:
        if media_path.exists():
            st.image(str(media_path), use_container_width=True)
        attribution = tutorial.get("attribution")
        if attribution:
            st.caption(str(attribution))

    with detail_col:
        st.markdown(
            f"""
            <span class="chip">{html.escape(id_istilah(tutorial.get('body_part')))}</span>
            <span class="chip">{html.escape(id_istilah(tutorial.get('equipment')))}</span>
            <span class="chip">{html.escape(id_istilah(tutorial.get('target')))}</span>
            """,
            unsafe_allow_html=True,
        )
        secondary = tutorial.get("secondary_muscles") or []
        if secondary:
            st.caption(f"Otot pendukung: {id_daftar(secondary)}")

        steps = (tutorial.get("instruction_steps") or {}).get("en") or []
        if not steps:
            instruction = (tutorial.get("instructions") or {}).get("en", "")
            steps = [instruction] if instruction else []

        st.markdown("**Langkah Pelaksanaan**")
        if not steps:
            st.write("Belum ada langkah pelaksanaan untuk latihan ini.")
            return

        for index, step in enumerate(id_langkah_latihan(steps), start=1):
            st.write(f"{index}. {step}")

        if lexicon_is_available():
            # Dataset tutorial menyediakan 10 bahasa dan Indonesia bukan salah
            # satunya, jadi teks di atas adalah hasil alih bahasa kamus istilah
            # latihan milik aplikasi ini. Teks aslinya tetap disediakan supaya
            # pengguna bisa memeriksa kalau ada kalimat yang terasa janggal.
            with st.expander("Lihat teks asli (Bahasa Inggris)"):
                for index, step in enumerate(steps, start=1):
                    st.write(f"{index}. {step}")
                render_original_description(exercise, embedded=True)
        else:
            st.caption(
                "Kamus terjemahan latihan belum tersedia, jadi langkah di atas "
                "masih ditampilkan dalam bahasa aslinya."
            )


def render_original_description(exercise: dict, *, embedded: bool = False) -> None:
    """Deskripsi asli berbahasa Inggris dari dataset utama.

    Keterangan yang tampil di halaman disusun dari metadata (lihat
    id_deskripsi_latihan), jadi prosa asli ini tidak hilang -- hanya dipindah ke
    tempat yang tidak mengganggu pembacaan utama.
    """
    description = str(exercise.get("Desc") or "").strip()
    if not description:
        return
    if embedded:
        st.markdown("**Deskripsi asli**")
        st.write(description)
        return
    with st.expander("Lihat deskripsi asli (Bahasa Inggris)"):
        st.write(description)
