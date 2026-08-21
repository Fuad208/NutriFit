"""Panel admin: kelola user, dataset makanan/latihan, performa model."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.database import CALORIE_STORE, MEAL_STORE, SQLStore, WORKOUT_STORE, delete_record, delete_user_and_related_data, latest_user_record, load_records, load_users
from src.recommender import clustering_performance_report

from ..core.data import get_data
from ..core.state import current_role, migrate_users


def admin_view(members: pd.DataFrame, foods: pd.DataFrame, exercises: pd.DataFrame) -> None:
    """Halaman admin: pintu masuk seluruh tab pengelolaan data, dijaga pemeriksaan role."""
    if current_role() != "admin":
        st.error("Halaman admin hanya bisa diakses oleh pengguna dengan peran admin.")
        return

    st.markdown('<div class="brand">Admin Data</div>', unsafe_allow_html=True)
    st.caption("Tinjau data pengguna terdaftar, anggota gym, makanan, dan latihan.")

    tab_users, tab_calorie, tab_meal, tab_workout, tab_performance, tab_members, tab_food, tab_exercise = st.tabs(
        [
            "Pengguna Terdaftar",
            "Data Kalori",
            "Data Menu",
            "Data Latihan",
            "Performa Model",
            "Anggota Gym",
            "Dataset Makanan",
            "Dataset Latihan",
        ]
    )
    with tab_users:
        admin_users_tab()
    with tab_calorie:
        admin_records_tab(CALORIE_STORE, "Kalori")
    with tab_meal:
        admin_records_tab(MEAL_STORE, "Rekomendasi menu")
    with tab_workout:
        admin_records_tab(WORKOUT_STORE, "Rekomendasi latihan")
    with tab_performance:
        admin_model_performance_tab(members, foods, exercises)
    with tab_members:
        st.dataframe(members, use_container_width=True, height=420)
    with tab_food:
        admin_food_dataset_tab(foods)
    with tab_exercise:
        admin_exercise_dataset_tab(exercises)


def admin_users_tab() -> None:
    """Tab pengguna: tabel akun terdaftar dan penghapusan akun non-admin beserta datanya."""
    users = migrate_users(load_users())
    rows = []
    for email, user in users.items():
        rows.append(
            {
                "user_id": user.get("user_id"),
                "name": user.get("name"),
                "email": email,
                "role": user.get("role", "user"),
                "gender": user.get("gender"),
                "birth_date": user.get("birth_date"),
                "has_calorie_data": bool(latest_user_record(CALORIE_STORE, user.get("user_id"))),
                "has_profile_snapshot": bool(user.get("profile")),
            }
        )

    st.dataframe(pd.DataFrame(rows), use_container_width=True, height=360)
    deletable_emails = [
        email
        for email, user in users.items()
        if email != st.session_state.current_user and user.get("role", "user") != "admin"
    ]
    if not deletable_emails:
        st.info("Saat ini tidak ada pengguna non-admin yang bisa dihapus.")
        return

    with st.form("delete_user_form"):
        email = st.selectbox("Pilih pengguna yang akan dihapus", deletable_emails)
        submitted = st.form_submit_button("Hapus Pengguna dan Seluruh Datanya", use_container_width=True)
    if submitted:
        st.session_state.admin_hapus = ("pengguna", email)
        st.rerun()

    if st.session_state.pop("admin_hapus_selesai", None):
        st.success(st.session_state.pop("admin_hapus_pesan", "Data berhasil dihapus."))

    sasaran = st.session_state.get("admin_hapus")
    if sasaran and sasaran[0] == "pengguna":
        konfirmasi_hapus_pengguna(sasaran[1])


@st.dialog("Hapus pengguna ini?")
def konfirmasi_hapus_pengguna(email: str) -> None:
    """Konfirmasi untuk aksi paling merusak di seluruh aplikasi.

    Menghapus pengguna ikut membuang SELURUH riwayat miliknya -- perhitungan
    kalori, rekomendasi menu, dan rekomendasi latihan. Tidak ada pemulihan.
    """
    jumlah = {
        "perhitungan kalori": len(load_user_records_count(CALORIE_STORE, email)),
        "rekomendasi menu": len(load_user_records_count(MEAL_STORE, email)),
        "rekomendasi latihan": len(load_user_records_count(WORKOUT_STORE, email)),
    }
    st.markdown(f"Akun **{email}** akan dihapus **permanen** beserta:")
    st.markdown("\n".join(f"- {n} catatan {label}" for label, n in jumlah.items()))
    st.warning("Tindakan ini tidak bisa dibatalkan dan datanya tidak bisa dipulihkan.")

    batal, hapus = st.columns(2)
    if batal.button("Batal", key="admin_user_cancel", use_container_width=True):
        st.session_state.admin_hapus = None
        st.rerun()
    if hapus.button("Ya, Hapus", key="admin_user_confirm", type="primary", use_container_width=True):
        delete_user_and_related_data(email)
        st.session_state.admin_hapus = None
        st.session_state.admin_hapus_selesai = True
        st.session_state.admin_hapus_pesan = f"Pengguna beserta seluruh datanya berhasil dihapus: {email}"
        st.rerun()


def load_user_records_count(store: str, email: str) -> list[dict]:
    """Ambil seluruh record pada satu store yang dimiliki satu alamat email."""
    return [r for r in load_records(store) if r.get("email") == email]


def admin_records_tab(store: str, label: str) -> None:
    """Tab riwayat (kalori/menu/latihan): tabel ringkasan dan penghapusan satu record."""
    records = load_records(store)
    if records:
        st.dataframe(pd.DataFrame([summarize_record(record) for record in records]), use_container_width=True, height=360)
    else:
        st.info(f"Belum ada data {label.lower()}.")
        return

    record_options = {
        f"{record.get('created_at', 'no-date')} | {record.get('email', '-')} | {record.get('id')}": record.get("id")
        for record in records
    }
    with st.form(f"delete_{store}_form"):
        selected = st.selectbox(f"Pilih data {label.lower()} yang akan dihapus", list(record_options.keys()))
        submitted = st.form_submit_button(f"Hapus Data {label}", use_container_width=True)
    if submitted:
        st.session_state.admin_hapus = ("record", store, label, selected, record_options[selected])
        st.rerun()

    if st.session_state.pop(f"hapus_selesai_{store}", None):
        st.success(f"Data {label.lower()} berhasil dihapus.")

    sasaran = st.session_state.get("admin_hapus")
    if sasaran and sasaran[0] == "record" and sasaran[1] == store:
        konfirmasi_hapus_record(store, sasaran[2], sasaran[3], sasaran[4])


@st.dialog("Hapus data ini?")
def konfirmasi_hapus_record(store: str, label: str, keterangan: str, record_id) -> None:
    """Dialog konfirmasi sebelum satu record riwayat dihapus permanen."""
    st.markdown(f"Satu data **{label.lower()}** akan dihapus **permanen**:")
    st.code(keterangan, language=None)
    st.warning("Tindakan ini tidak bisa dibatalkan.")

    batal, hapus = st.columns(2)
    if batal.button("Batal", key=f"rec_cancel_{store}", use_container_width=True):
        st.session_state.admin_hapus = None
        st.rerun()
    if hapus.button(
        "Ya, Hapus", key=f"rec_confirm_{store}", type="primary", use_container_width=True
    ):
        delete_record(store, record_id)
        st.session_state.admin_hapus = None
        st.session_state[f"hapus_selesai_{store}"] = True
        st.rerun()


def admin_model_performance_tab(members: pd.DataFrame, foods: pd.DataFrame, exercises: pd.DataFrame) -> None:
    """Tab performa: metrik ketiga algoritma klasterisasi atas dataset yang sedang aktif."""
    st.caption("Evaluasi clustering berdasarkan dataset yang sedang aktif di sistem.")
    if st.button("Refresh Performa Model", use_container_width=True):
        get_data.clear()
        st.rerun()

    report = clustering_performance_report(members, foods, exercises)
    for title, payload in report.items():
        st.markdown(f"### {title}")
        cols = st.columns(5)
        cols[0].metric("Algoritma", payload["algorithm"])
        cols[1].metric("Tipe Data", payload["data_type"])
        cols[2].metric("Jumlah Data", f"{payload['rows']:,}")
        cols[3].metric("Jumlah Klaster", payload["n_clusters"])
        skor = payload["score"]
        cols[4].metric(payload["score_label"],
                       "-" if skor is None else f"{skor:,.3f}")

        metric_cols = st.columns([0.35, 0.65])
        with metric_cols[0]:
            st.metric(payload["cost_label"], f"{payload['cost']:,.3f}")
            # Sebagian algoritma dinilai lebih dari satu metrik -- K-Means
            # memakai Calinski-Harabasz dan Silhouette sekaligus.
            for nama, nilai in (payload.get("extra_scores") or {}).items():
                st.metric(nama, "-" if nilai is None else f"{nilai:,.3f}")
        metric_cols[1].dataframe(payload["counts"], use_container_width=True, hide_index=True)
        st.divider()


def admin_food_dataset_tab(foods: pd.DataFrame) -> None:
    """Tab dataset makanan: tabel, formulir tambah/ubah, dan penghapusan data."""
    st.dataframe(
        foods[["id", "name", "calories", "proteins", "fat", "carbohydrate", "Food_Cluster"]],
        use_container_width=True,
        height=300,
    )
    with st.expander("Tambah / Ubah Data Makanan"):
        food_ids = sorted(foods["id"].dropna().astype(int).tolist())
        mode = st.radio("Mode Makanan", ["Tambah", "Ubah"], horizontal=True)
        selected_id = None
        selected_food = {}
        if mode == "Ubah" and food_ids:
            selected_id = st.selectbox("Pilih ID makanan", food_ids)
            selected_food = foods[foods["id"] == selected_id].iloc[0].to_dict()

        with st.form("food_dataset_form"):
            food_id = st.number_input(
                "ID",
                min_value=1,
                value=int(selected_id or next_numeric_id(food_ids)),
                step=1,
                disabled=mode == "Ubah",
            )
            name = st.text_input("Nama Makanan", value=str(selected_food.get("name", "")))
            calories = st.number_input("Kalori", min_value=0.0, value=safe_float(selected_food.get("calories")))
            proteins = st.number_input("Protein", min_value=0.0, value=safe_float(selected_food.get("proteins")))
            fat = st.number_input("Lemak", min_value=0.0, value=safe_float(selected_food.get("fat")))
            carbohydrate = st.number_input("Karbohidrat", min_value=0.0, value=safe_float(selected_food.get("carbohydrate")))
            image = st.text_input("URL Gambar", value=str(selected_food.get("image", "") or ""))
            submitted = st.form_submit_button("Simpan Data Makanan", use_container_width=True)

        if submitted:
            if not name.strip():
                st.error("Nama makanan wajib diisi.")
            else:
                upsert_food_record(
                    {
                        "id": int(selected_id or food_id),
                        "calories": calories,
                        "proteins": proteins,
                        "fat": fat,
                        "carbohydrate": carbohydrate,
                        "name": name.strip(),
                        "image": image.strip(),
                    }
                )
                refresh_datasets_after_admin_change("Data makanan berhasil disimpan.")

    with st.expander("Hapus Data Makanan"):
        food_ids = sorted(foods["id"].dropna().astype(int).tolist())
        if not food_ids:
            st.info("Belum ada data makanan.")
            return
        with st.form("delete_food_dataset_form"):
            food_id = st.selectbox("Pilih ID makanan yang dihapus", food_ids)
            submitted = st.form_submit_button("Hapus Data Makanan", use_container_width=True)
        if submitted:
            delete_dataset_record("food_nutrition", "id", int(food_id))
            refresh_datasets_after_admin_change("Data makanan berhasil dihapus.")


def admin_exercise_dataset_tab(exercises: pd.DataFrame) -> None:
    """Tab dataset latihan: tabel, formulir tambah/ubah, dan penghapusan data."""
    exercises = ensure_exercise_ids(exercises)
    visible_columns = ["Program_ID", "Title", "Type", "BodyPart", "Equipment", "Level", "Exercise_Cluster"]
    st.dataframe(exercises[visible_columns], use_container_width=True, height=300)
    exercise_ids = sorted(exercises["Program_ID"].dropna().astype(int).tolist())
    with st.expander("Tambah / Ubah Data Latihan"):
        mode = st.radio("Mode Latihan", ["Tambah", "Ubah"], horizontal=True)
        selected_id = None
        selected_exercise = {}
        if mode == "Ubah" and exercise_ids:
            selected_id = st.selectbox("Pilih ID program", exercise_ids)
            selected_exercise = exercises[exercises["Program_ID"] == selected_id].iloc[0].to_dict()

        with st.form("exercise_dataset_form"):
            program_id = st.number_input(
                "ID Program",
                min_value=0,
                value=int(selected_id if selected_id is not None else next_numeric_id(exercise_ids, start=0)),
                step=1,
                disabled=mode == "Ubah",
            )
            title = st.text_input("Nama Latihan", value=str(selected_exercise.get("Title", "")))
            description = st.text_area("Deskripsi", value=str(selected_exercise.get("Desc", "") or ""))
            workout_type = st.text_input("Jenis Latihan", value=str(selected_exercise.get("Type", "")))
            body_part = st.text_input("Target Otot", value=str(selected_exercise.get("BodyPart", "")))
            equipment = st.text_input("Alat", value=str(selected_exercise.get("Equipment", "")))
            level = st.selectbox(
                "Level",
                ["Beginner", "Intermediate", "Expert"],
                index=["Beginner", "Intermediate", "Expert"].index(
                    selected_exercise.get("Level", "Beginner")
                    if selected_exercise.get("Level", "Beginner") in ["Beginner", "Intermediate", "Expert"]
                    else "Beginner"
                ),
            )
            rating = st.number_input("Rating", min_value=0.0, value=safe_float(selected_exercise.get("Rating")))
            rating_desc = st.text_input("Deskripsi Rating", value=str(selected_exercise.get("RatingDesc", "") or ""))
            submitted = st.form_submit_button("Simpan Data Latihan", use_container_width=True)

        if submitted:
            if not title.strip() or not workout_type.strip() or not body_part.strip() or not equipment.strip():
                st.error("Nama, jenis latihan, target otot, dan alat wajib diisi.")
            else:
                upsert_exercise_record(
                    {
                        "program_id": int(selected_id if selected_id is not None else program_id),
                        "title": title.strip(),
                        "description": description.strip(),
                        "type": workout_type.strip(),
                        "body_part": body_part.strip(),
                        "equipment": equipment.strip(),
                        "level": level,
                        "rating": rating,
                        "rating_desc": rating_desc.strip(),
                    }
                )
                refresh_datasets_after_admin_change("Data latihan berhasil disimpan.")

    with st.expander("Hapus Data Latihan"):
        if not exercise_ids:
            st.info("Belum ada data latihan.")
            return
        with st.form("delete_exercise_dataset_form"):
            program_id = st.selectbox("Pilih ID program yang dihapus", exercise_ids)
            submitted = st.form_submit_button("Hapus Data Latihan", use_container_width=True)
        if submitted:
            delete_dataset_record("training_program", "program_id", int(program_id))
            refresh_datasets_after_admin_change("Data latihan berhasil dihapus.")


def ensure_exercise_ids(exercises: pd.DataFrame) -> pd.DataFrame:
    """Pastikan kolom Program_ID tersedia; dibuat dari indeks bila dataset belum punya."""
    exercises = exercises.copy()
    if "Program_ID" not in exercises.columns:
        exercises.insert(0, "Program_ID", exercises.index.astype(int))
    return exercises


def next_numeric_id(values: list[int], start: int = 1) -> int:
    """ID berikutnya untuk data baru, yaitu satu di atas ID terbesar yang ada."""
    return (max(values) + 1) if values else start


def safe_float(value) -> float:
    """Ubah nilai jadi float; balas 0.0 bila kosong, NaN, atau tidak bisa dikonversi."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if pd.isna(number):
        return 0.0
    return number


def upsert_food_record(record: dict) -> None:
    """Simpan satu baris dataset makanan (tambah bila baru, perbarui bila ID sudah ada)."""
    store = SQLStore()
    columns = ["id", "calories", "proteins", "fat", "carbohydrate", "name", "image"]
    upsert_dataset_record(store, "food_nutrition", "id", columns, record)


def upsert_exercise_record(record: dict) -> None:
    """Simpan satu baris dataset latihan (tambah bila baru, perbarui bila ID sudah ada)."""
    store = SQLStore()
    columns = ["program_id", "title", "description", "type", "body_part", "equipment", "level", "rating", "rating_desc"]
    upsert_dataset_record(store, "training_program", "program_id", columns, record)


def upsert_dataset_record(store: SQLStore, table: str, primary_key: str, columns: list[str], record: dict) -> None:
    """Jalankan INSERT dengan klausa upsert untuk satu baris tabel dataset."""
    placeholders = ", ".join([store.placeholder()] * len(columns))
    updates = ", ".join(dataset_update_clause(columns, primary_key))
    sql = f"""
        INSERT INTO {table} ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT ({primary_key}) DO UPDATE SET {updates}
    """
    with store.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(record.get(column) for column in columns))


def dataset_update_clause(columns: list[str], primary_key: str) -> list[str]:
    """Susun bagian SET pada klausa upsert, mengecualikan kolom kunci primer."""
    return [f"{column}=EXCLUDED.{column}" for column in columns if column != primary_key]


def delete_dataset_record(table: str, primary_key: str, record_id: int) -> None:
    """Hapus satu baris tabel dataset berdasarkan kunci primernya."""
    store = SQLStore()
    with store.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {table} WHERE {primary_key} = {store.placeholder()}", (record_id,))


def refresh_datasets_after_admin_change(message: str) -> None:
    """Kosongkan cache dataset dan rekomendasi di sesi setelah data diubah, lalu tampilkan pesan sukses."""
    get_data.clear()
    st.session_state.food_recommendations = None
    st.session_state.exercise_recommendations = None
    st.session_state.workout_filters = None
    st.session_state.excluded_exercise_titles = []
    st.success(message)
    st.rerun()


def summarize_record(record: dict) -> dict:
    """Ringkas satu record jadi baris tabel: kolom identitas plus kolom khas jenis record itu."""
    summary = {
        "id": record.get("id"),
        "user_id": record.get("user_id"),
        "email": record.get("email"),
        "created_at": record.get("created_at"),
    }
    if "profile" in record:
        profile = record.get("profile") or {}
        nutrition = record.get("nutrition") or {}
        summary.update(
            {
                "fitness_goal": profile.get("fitness_goal"),
                "activity_level": profile.get("activity_level"),
                "experience_level": profile.get("experience_level"),
                "target_calories": nutrition.get("target_calories"),
                "bmi": nutrition.get("bmi"),
            }
        )
    if "preference" in record:
        summary["preference"] = record.get("preference")
        summary["meal_slots"] = len(record.get("recommendations", {}))
    if "filters" in record:
        filters = record.get("filters") or {}
        summary.update(filters)
        summary["exercise_count"] = len(record.get("recommendations", []))
    return {key: _nilai_tabel(value) for key, value in summary.items()}


def _nilai_tabel(value):
    """Ratakan nilai bersarang menjadi satu sel tabel yang bisa dibaca.

    `preference` berisi DAFTAR label kategori sejak filter preferensi diubah
    dari kata kunci bebas menjadi pilihan kategori. pyarrow -- yang dipakai
    st.dataframe untuk menserialisasi tabel -- tidak bisa menaruh list di dalam
    satu kolom, sehingga seluruh tabel gagal dikonversi:

        ArrowTypeError: Expected bytes, got a 'list' object
        Conversion failed for column preference with type object

    Streamlit memang memulihkan diri dengan memaksa kolomnya jadi teks, tetapi
    sebelum itu ia membuang traceback panjang ke konsol tiap kali tab dibuka.
    Diratakan di sini supaya tabelnya benar sejak awal, bukan hasil pemulihan
    darurat. Ditulis umum, bukan khusus `preference`, karena kolom lain (mis.
    isi `filters`) bisa ikut berisi list di kemudian hari.
    """
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value) if value else ""
    if isinstance(value, dict):
        return ", ".join(f"{key}: {item}" for key, item in value.items()) if value else ""
    return value
