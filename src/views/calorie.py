"""Halaman kalkulator kalori & riwayat transaksi kalori."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from datetime import date

from src.database import CALORIE_STORE, delete_record, latest_user_record, load_records, load_users, save_users
from src.nutrition import NutritionResult, calculate_nutrition_targets
from src.recommender import assign_user_cluster, profile_payload

from ..core.components import format_record_datetime, metric_card
from ..core.state import calculate_age_from_birth_date, current_user, migrate_users, parse_birth_date, persist_user_profile


def calorie_view(members: pd.DataFrame) -> None:
    """Halaman kalkulator: isi data fisik dan gaya hidup, hitung target gizi, lalu simpan hasilnya."""
    st.markdown('<div class="brand">Hitung Nutrisi</div>', unsafe_allow_html=True)
    st.caption("Masukkan data fisik dan gaya hidup Anda untuk mendapatkan rekomendasi kalori dan makronutrisi harian.")

    user = st.session_state.users.get(st.session_state.current_user, {})
    default_gender = user.get("gender", "Male")
    birth_date = parse_birth_date(user.get("birth_date", date(2000, 1, 1)))
    age = calculate_age_from_birth_date(birth_date, minimum=13)
    activity_options = {
        "Ringan (Jarang Olahraga)": "Low",
        "Sedang (Olahraga ringan 1-3 hari per minggu)": "Medium",
        "Tinggi (Olahraga intens 6-7 hari per minggu)": "High",
        "Sangat Tinggi (Atlet profesional)": "Very High",
    }
    experience_options = {"Pemula": "Beginner", "Menengah": "Intermediate", "Ahli": "Expert"}
    goal_options = {
        "Menurunkan Berat": "Lose Weight",
        "Menjaga Berat": "Maintain Weight",
        "Menaikkan Berat": "Gain Weight",
    }

    with st.form("calorie_form"):
        body_cols = st.columns(2)
        with body_cols[0]:
            weight = st.number_input("Berat (kg)", min_value=30.0, max_value=250.0, value=70.0, step=0.5)
        with body_cols[1]:
            height = st.number_input("Tinggi (cm)", min_value=120.0, max_value=230.0, value=175.0, step=0.5)

        habit_cols = st.columns(2)
        with habit_cols[0]:
            activity_label = st.selectbox("Tingkat Aktivitas", list(activity_options), index=1)
        with habit_cols[1]:
            experience_label = st.selectbox("Level Pengalaman", list(experience_options), index=1)

        goal_label = st.radio("Tujuan", list(goal_options), horizontal=True)

        submitted = st.form_submit_button("Hitung Sekarang", use_container_width=True)

    if submitted:
        gender = default_gender
        activity_level = activity_options[activity_label]
        experience = experience_options[experience_label]
        goal = goal_options[goal_label]
        nutrition = calculate_nutrition_targets(
            gender=gender,
            weight_kg=weight,
            height_cm=height,
            age=int(age),
            activity_level=activity_level,
            fitness_goal=goal,
        )
        profile = {
            "gender": gender,
            "age": int(age),
            "weight_kg": weight,
            "height_cm": height,
            "activity_level": activity_level,
            "experience_level": experience,
            "fitness_goal": goal,
            "bmi": nutrition.bmi,
        }
        profile["user_cluster"] = assign_user_cluster(members, profile)
        st.session_state.nutrition = nutrition
        st.session_state.profile = profile_payload(nutrition, **profile)
        if persist_user_profile(st.session_state.profile, nutrition):
            st.success("Profil nutrisi berhasil dihitung dan disimpan ke riwayat.")
        else:
            st.info(
                "Profil nutrisi diperbarui. Perhitungan dengan data yang sama persis "
                "sudah tercatat hari ini, jadi riwayat tidak ditambah entri kembar."
            )

    if st.session_state.nutrition:
        show_nutrition_result(st.session_state.nutrition, st.session_state.profile)
    show_calorie_transactions()


def show_nutrition_result(nutrition, profile) -> None:
    """Tampilkan ringkasan kesehatan dan target harian dari hasil perhitungan terakhir."""
    bmi_status_map = {
        "Underweight": "Berat Badan Kurang",
        "Kurus": "Berat Badan Kurang",
        "Normal": "Normal",
        "Overweight": "Berat Badan Berlebih",
        "Gemuk": "Gemuk",
        "Obese": "Obesitas",
        "Obesitas I": "Obesitas I",
        "Obesitas II": "Obesitas II",
    }
    st.markdown('<div class="section-title">Ringkasan Kesehatan</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    for col, (label, value) in zip(
        cols,
        [
            ("BMI", f"{nutrition.bmi} - {bmi_status_map.get(nutrition.bmi_status, nutrition.bmi_status)}"),
            ("BMR", f"{nutrition.bmr:,.0f} kkal"),
            ("TDEE", f"{nutrition.tdee:,.0f} kkal"),
            ("Berat Ideal", f"{nutrition.ideal_weight} kg"),
        ],
    ):
        with col:
            metric_card(label, value)

    st.markdown('<div class="section-title">Target Nutrisi Harian</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    for col, (label, value) in zip(
        cols,
        [
            ("Target Kalori", f"{nutrition.target_calories:,.0f} kkal/hari"),
            ("Karbohidrat", f"{nutrition.carbohydrate_g:,.0f} g"),
            ("Protein", f"{nutrition.protein_g:,.0f} g"),
            ("Lemak", f"{nutrition.fat_g:,.0f} g"),
        ],
    ):
        with col:
            metric_card(label, value)
    # Diambil dengan .get(): profil di sini bisa berasal dari record LAMA yang
    # dipulihkan sync_current_nutrition_from_records setelah sebuah riwayat
    # dihapus, dan record yang dibuat sebelum segmentasi anggota ada belum
    # memuat kunci ini. Indeks langsung membuat seluruh halaman gagal render.
    segmen = profile.get("user_cluster") if isinstance(profile, dict) else None
    if segmen is not None:
        st.caption(f"Segmen pengguna: Klaster {segmen}")


def show_calorie_transactions() -> None:
    """Tabel riwayat perhitungan kalori milik pengguna berikut aksi hapus per baris."""
    user = current_user()
    user_id = user.get("user_id")
    records = [
        record
        for record in load_records(CALORIE_STORE)
        if record.get("user_id") == user_id
    ]
    records = sorted(records, key=lambda record: record.get("created_at", ""), reverse=True)

    st.markdown('<div class="section-title">Riwayat Perhitungan Kalori</div>', unsafe_allow_html=True)

    # Pesan sukses ditampilkan SETELAH dialog tertutup: st.rerun() di dalam
    # dialog menutupnya sekaligus membuang apa pun yang dirender di sana, jadi
    # konfirmasi keberhasilan harus muncul di halaman induknya.
    if st.session_state.pop("calorie_delete_done", False):
        st.success("Transaksi kalori berhasil dihapus.")

    if not records:
        st.info("Belum ada transaksi hitung kalori.")
        return

    header_cols = st.columns([1.7, 1, 1, 1, 1, 1, 0.8])
    for col, label in zip(
        header_cols,
        ["Tanggal", "Berat", "BMI", "Target", "Protein", "Tujuan", "Aksi"],
    ):
        col.caption(label)

    for record in records:
        profile = record.get("profile") or {}
        nutrition = record.get("nutrition") or {}
        row_cols = st.columns([1.7, 1, 1, 1, 1, 1, 0.8])
        row_cols[0].write(format_record_datetime(record.get("created_at")))
        row_cols[1].write(f"{format_number(profile.get('weight_kg'))} kg")
        row_cols[2].write(format_number(nutrition.get("bmi") or profile.get("bmi")))
        row_cols[3].write(f"{format_number(nutrition.get('target_calories'))} kkal")
        row_cols[4].write(f"{format_number(nutrition.get('protein_g'))} g")
        row_cols[5].write(goal_label(profile.get("fitness_goal")))
        if row_cols[6].button("Hapus", key=f"delete_calorie_{record.get('id')}", use_container_width=True):
            # Tidak langsung menghapus. Tombolnya hanya menandai baris mana yang
            # dimaksud, lalu dialog konfirmasi yang memutuskan -- penghapusan ini
            # permanen dan bisa ikut mengubah target kalori harian yang sedang
            # dipakai, jadi satu klik tidak boleh cukup.
            st.session_state.calorie_delete_id = record.get("id")
            st.rerun()

    if st.session_state.get("calorie_delete_id"):
        target = next(
            (r for r in records if r.get("id") == st.session_state.calorie_delete_id),
            None,
        )
        if target is None:
            # Barisnya sudah tidak ada (mis. terhapus di tab lain).
            st.session_state.calorie_delete_id = None
        else:
            confirm_delete_calorie(target, records, user_id)


@st.dialog("Hapus riwayat perhitungan?")
def confirm_delete_calorie(record: dict, records: list[dict], user_id: str | None) -> None:
    """Dialog konfirmasi sebelum satu riwayat perhitungan dihapus permanen."""
    profile = record.get("profile") or {}
    nutrition = record.get("nutrition") or {}
    paling_baru = bool(records) and records[0].get("id") == record.get("id")

    st.markdown("Data berikut akan dihapus **permanen** dan tidak bisa dikembalikan:")
    st.markdown(
        f"- **Tanggal** {format_record_datetime(record.get('created_at'))}\n"
        f"- **Berat** {format_number(profile.get('weight_kg'))} kg &nbsp;·&nbsp; "
        f"**BMI** {format_number(nutrition.get('bmi') or profile.get('bmi'))}\n"
        f"- **Target** {format_number(nutrition.get('target_calories'))} kkal &nbsp;·&nbsp; "
        f"**Tujuan** {goal_label(profile.get('fitness_goal'))}"
    )

    # Peringatan yang paling penting: menghapus catatan TERBARU bukan sekadar
    # membuang satu baris riwayat, tetapi mengganti target kalori harian yang
    # sedang berlaku dengan catatan sebelumnya -- atau mengosongkannya sama
    # sekali kalau ini satu-satunya catatan yang tersisa.
    if paling_baru:
        if len(records) > 1:
            sebelumnya = (records[1].get("nutrition") or {}).get("target_calories")
            st.warning(
                "Ini catatan terbaru Anda. Setelah dihapus, target kalori harian "
                f"akan mengikuti catatan sebelumnya "
                f"({format_number(sebelumnya)} kkal)."
            )
        else:
            st.warning(
                "Ini satu-satunya catatan Anda. Setelah dihapus, target kalori dan "
                "makro harian menjadi kosong, dan rekomendasi menu maupun latihan "
                "tidak bisa dibuat sampai Anda menghitung ulang."
            )

    batal_col, hapus_col = st.columns(2)
    if batal_col.button("Batal", key="calorie_delete_cancel", use_container_width=True):
        st.session_state.calorie_delete_id = None
        st.rerun()
    if hapus_col.button(
        "Ya, Hapus", key="calorie_delete_confirm", type="primary", use_container_width=True
    ):
        delete_record(CALORIE_STORE, record.get("id"))
        sync_current_nutrition_from_records(user_id)
        st.session_state.calorie_delete_id = None
        st.session_state.calorie_delete_done = True
        st.rerun()


def format_number(value) -> str:
    """Format angka dengan pemisah ribuan; bilangan bulat tanpa desimal, sisanya satu desimal."""
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{number:,.0f}"
    return f"{number:,.1f}"


def goal_label(value: str | None) -> str:
    """Terjemahkan kode tujuan latihan ke label singkat berbahasa Indonesia."""
    labels = {
        "Lose Weight": "Turun",
        "Maintain Weight": "Jaga",
        "Gain Weight": "Naik",
    }
    return labels.get(value or "", value or "-")


def sync_current_nutrition_from_records(user_id: str | None) -> None:
    """Selaraskan profil dan target gizi di sesi maupun akun dengan record kalori terbaru."""
    email = st.session_state.current_user
    if not email or not user_id:
        return

    latest_record = latest_user_record(CALORIE_STORE, user_id)
    st.session_state.users = migrate_users(load_users())
    user = st.session_state.users.get(email)
    if not user:
        return

    if latest_record:
        profile = latest_record.get("profile")
        nutrition = latest_record.get("nutrition")
        user["profile"] = profile
        user["nutrition"] = nutrition
        st.session_state.profile = profile
        st.session_state.nutrition = NutritionResult(**nutrition) if nutrition else None
    else:
        user.pop("profile", None)
        user.pop("nutrition", None)
        st.session_state.profile = None
        st.session_state.nutrition = None

    save_users(st.session_state.users)
