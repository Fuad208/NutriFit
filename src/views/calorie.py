"""Halaman kalkulator kalori & riwayat transaksi kalori."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from datetime import date

from src.database import CALORIE_STORE, delete_record, latest_user_record, load_records, load_users, save_users
from src.nutrition import NutritionResult, calculate_nutrition_targets, goal_guardrail
from src.recommender import assign_user_cluster, profile_payload

from ..core.components import format_record_datetime, metric_card
from ..core.state import calculate_age_from_birth_date, current_user, migrate_users, parse_birth_date, persist_user_profile


# Rumus Broca (tinggi - 100, dikoreksi 10-15%) yang dipakai calculate_ideal_weight
# runtuh di tinggi rendah: pada 120 cm ia memberi 18 kg, sedangkan rentang BMI
# normal untuk tinggi itu 26,6-33,1 kg. Keduanya baru sejalan mulai sekitar
# 148 cm. Batas bawahnya dinaikkan ke 140 cm supaya "Berat Ideal" dan "rentang
# berat sehat" tidak pernah tampil bertentangan di layar yang sama.
MIN_HEIGHT_CM = 140.0

BMI_STATUS_LABELS = {
    "Underweight": "Berat Badan Kurang",
    "Kurus": "Berat Badan Kurang",
    "Normal": "Normal",
    "Overweight": "Berat Badan Berlebih",
    "Gemuk": "Gemuk",
    "Obese": "Obesitas",
    "Obesitas I": "Obesitas I",
    "Obesitas II": "Obesitas II",
}


def clamp_number(value, minimum: float, maximum: float, fallback: float) -> float:
    """Angka tersimpan yang dijamin masuk rentang widget, atau nilai bawaan bila tidak terpakai.

    Record lama bisa memuat tinggi di bawah MIN_HEIGHT_CM, dan st.number_input
    melempar exception bila `value` di luar [min_value, max_value].
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(max(number, minimum), maximum)


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

    goal_labels = {value: label for label, value in goal_options.items()}

    # Nilai bawaan diambil dari perhitungan terakhir pengguna, bukan angka tetap,
    # 70 kg / 175 cm, sehingga pengguna lama selalu mulai dari angka yang bukan
    # miliknya dan harus mengetik ulang setiap kali membuka halaman ini.
    tersimpan = user.get("profile") or {}
    berat_awal = clamp_number(tersimpan.get("weight_kg"), 30.0, 250.0, 70.0)
    tinggi_awal = clamp_number(tersimpan.get("height_cm"), MIN_HEIGHT_CM, 230.0, 170.0)

    # Berat dan tinggi sengaja berada di LUAR st.form. Streamlit menahan nilai
    # widget di dalam form sampai tombol kirim ditekan, sehingga IMT belum diketahui
    # saat pilihan Tujuan dirender -- dan pagar tujuan tidak bisa bekerja.
    # Lihat docs/catatan-desain.md bagian 13.
    body_cols = st.columns(2)
    with body_cols[0]:
        weight = st.number_input("Berat (kg)", min_value=30.0, max_value=250.0, value=berat_awal, step=0.5)
    with body_cols[1]:
        height = st.number_input(
            "Tinggi (cm)", min_value=MIN_HEIGHT_CM, max_value=230.0, value=tinggi_awal, step=0.5
        )

    pagar = goal_guardrail(weight, height)
    bmi_cols = st.columns(2)
    with bmi_cols[0]:
        metric_card("BMI", f"{pagar.bmi} - {BMI_STATUS_LABELS.get(pagar.bmi_status, pagar.bmi_status)}")
    with bmi_cols[1]:
        metric_card("Rentang Berat Sehat", f"{pagar.weight_min} - {pagar.weight_max} kg")

    habit_cols = st.columns(2)
    with habit_cols[0]:
        activity_label = st.selectbox("Tingkat Aktivitas", list(activity_options), index=1)
    with habit_cols[1]:
        experience_label = st.selectbox("Level Pengalaman", list(experience_options), index=1)

    goal = render_goal_choice(pagar, goal_labels)
    submitted = st.button("Hitung Sekarang", use_container_width=True, disabled=goal is None)

    if submitted and goal is not None:
        gender = default_gender
        activity_level = activity_options[activity_label]
        experience = experience_options[experience_label]
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


def render_goal_choice(pagar, goal_labels: dict) -> str | None:
    """Tampilkan pilihan tujuan sesuai pagar BMI; None berarti belum boleh dihitung.

    Tujuan yang diblokir tidak dirender sama sekali. Menampilkannya lalu menolak
    saat tombol ditekan hanya memindahkan kekecewaan ke belakang, dan pengguna
    tetap tidak tahu kenapa pilihannya ditolak.
    """
    kategori = BMI_STATUS_LABELS.get(pagar.bmi_status, pagar.bmi_status)
    rentang = f"Rentang berat sehat Anda {pagar.weight_min}-{pagar.weight_max} kg."

    # Satu-satunya pilihan tidak perlu dirender sebagai pilihan: radio berisi satu
    # opsi terbaca seperti pilihan palsu. Kondisinya dinyatakan saja, lengkap
    # dengan alasannya, supaya keputusannya tidak terasa sewenang-wenang.
    if pagar.fixed:
        st.info(
            f"BMI Anda {pagar.bmi} ({kategori}). Tujuan ditetapkan: "
            f"**{goal_labels[pagar.fixed]}**. {rentang}"
        )
        return pagar.fixed

    pilihan = list(pagar.allowed)
    label = st.radio(
        "Tujuan",
        [goal_labels[goal] for goal in pilihan],
        index=pilihan.index(pagar.default),
        horizontal=True,
    )
    goal = {goal_labels[item]: item for item in pilihan}[label]
    tingkat = pagar.level(goal)

    if tingkat == "error":
        arah = "menaikkan" if goal == "Gain Weight" else "menurunkan"
        st.error(
            f"BMI Anda {pagar.bmi} ({kategori}). {arah.capitalize()} berat badan "
            f"tidak disarankan untuk kondisi ini. {rentang}"
        )
        # Kuncinya dibedakan per tujuan supaya persetujuan untuk satu tujuan tidak
        # ikut terbawa saat pengguna berpindah ke tujuan lain yang juga berisiko.
        if not st.checkbox(
            "Saya mengerti risikonya dan tetap ingin melanjutkan",
            key=f"konfirmasi_tujuan_{goal}",
        ):
            return None
    elif tingkat == "warning":
        st.warning(
            f"BMI Anda {pagar.bmi} ({kategori}). Menurunkan berat badan lebih "
            f"dianjurkan untuk kondisi ini. {rentang}"
        )
    elif tingkat == "syarat":
        arah = "menaikkan" if goal == "Gain Weight" else "menurunkan"
        batas = pagar.weight_max if goal == "Gain Weight" else pagar.weight_min
        st.info(
            f"Berat badan Anda sudah Normal. Anda boleh {arah} berat hingga {batas} kg — "
            f"di luar itu Anda keluar dari rentang sehat "
            f"{pagar.weight_min}-{pagar.weight_max} kg."
        )
    return goal


def show_nutrition_result(nutrition, profile) -> None:
    """Tampilkan ringkasan kesehatan dan target harian dari hasil perhitungan terakhir."""
    st.markdown('<div class="section-title">Ringkasan Kesehatan</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    for col, (label, value) in zip(
        cols,
        [
            ("BMI", f"{nutrition.bmi} - {BMI_STATUS_LABELS.get(nutrition.bmi_status, nutrition.bmi_status)}"),
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
        # Keterangannya sengaja menyebut apa yang dikerjakan segmen ini DAN apa
        # yang tidak. Menampilkan nomor klaster tanpa penjelasan membuat pengguna
        # menduga menunya disusun berdasarkan segmen itu, padahal target kalori
        # dan porsinya dihitung dari tubuhnya sendiri -- di dalam satu segmen,
        # kebutuhan energi anggotanya bisa berselisih sampai 2.000 kkal/hari.
        st.caption(
            f"Segmen pengguna: Klaster {segmen} — kelompok anggota dengan tujuan "
            f"kebugaran serupa. Target kalori dan porsi menu Anda tetap dihitung "
            f"dari data tubuh Anda sendiri, bukan dari rata-rata segmen."
        )


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
