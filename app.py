from __future__ import annotations

from datetime import date, datetime
import hashlib
import html
from pathlib import Path
from uuid import uuid4

import altair as alt
import pandas as pd
import streamlit as st

from src.database import (
    CALORIE_DB_PATH,
    MEAL_DB_PATH,
    WORKOUT_DB_PATH,
    SQLStore,
    append_record,
    delete_record,
    delete_user_and_related_data,
    ensure_database,
    latest_user_record,
    load_records,
    load_users,
    save_users,
    using_sql,
)
from src.nutrition import calculate_nutrition_targets
from src.nutrition import NutritionResult
from src.recommender import (
    assign_user_cluster,
    clustering_performance_report,
    load_datasets,
    profile_payload,
    recommend_exercises,
    recommend_foods,
    swap_food,
)


st.set_page_config(
    page_title="NutriFit",
    page_icon="N",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(show_spinner=False)
def get_data():
    return load_datasets()


def init_state() -> None:
    ensure_database()
    defaults = {
        "authenticated": False,
        "users": migrate_users(load_users()),
        "current_user": None,
        "page": "Login",
        "nutrition": None,
        "profile": None,
        "food_recommendations": None,
        "exercise_recommendations": None,
        "excluded_food_ids": [],
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def migrate_users(users: dict) -> dict:
    migrated = False
    for email, user in users.items():
        if "user_id" not in user:
            user["user_id"] = str(uuid4())
            migrated = True
        if "role" not in user:
            user["role"] = "user"
            migrated = True
        if "email" not in user:
            user["email"] = email
            migrated = True
    if migrated:
        save_users(users)
    return users


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(user: dict, password: str) -> bool:
    hashed = hash_password(password)
    stored_password = user.get("password")
    stored_password_hash = user.get("password_hash")
    return stored_password == hashed or stored_password_hash == hashed or stored_password == password


def current_user() -> dict:
    st.session_state.users = migrate_users(load_users())
    return st.session_state.users.get(st.session_state.current_user, {})


def current_role() -> str:
    return current_user().get("role", "user")


def restore_user_context(email: str) -> None:
    user = st.session_state.users.get(email, {})
    calorie_record = latest_user_record(CALORIE_DB_PATH, user.get("user_id"))
    profile = calorie_record.get("profile") if calorie_record else user.get("profile")
    nutrition = calorie_record.get("nutrition") if calorie_record else user.get("nutrition")
    if profile and nutrition:
        st.session_state.profile = profile
        st.session_state.nutrition = NutritionResult(**nutrition)
    else:
        st.session_state.profile = None
        st.session_state.nutrition = None
    st.session_state.food_recommendations = None
    st.session_state.exercise_recommendations = None
    st.session_state.excluded_food_ids = []


def persist_user_profile(profile: dict, nutrition: NutritionResult) -> None:
    email = st.session_state.current_user
    if not email:
        return
    st.session_state.users = migrate_users(load_users())
    user = st.session_state.users.get(email)
    if not user:
        return
    user_id = user["user_id"]
    user["profile"] = profile
    user["nutrition"] = nutrition.__dict__
    save_users(st.session_state.users)
    append_record(
        CALORIE_DB_PATH,
        {
            "id": str(uuid4()),
            "user_id": user_id,
            "email": email,
            "profile": profile,
            "nutrition": nutrition.__dict__,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
    )


def persist_meal_recommendation(recommendations: dict, preference: list[str]) -> None:
    user = current_user()
    if not user:
        return
    append_record(
        MEAL_DB_PATH,
        {
            "id": str(uuid4()),
            "user_id": user["user_id"],
            "email": user["email"],
            "preference": preference,
            "recommendations": recommendations,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
    )


def persist_workout_recommendation(recommendations: pd.DataFrame, filters: dict) -> None:
    user = current_user()
    if not user:
        return
    append_record(
        WORKOUT_DB_PATH,
        {
            "id": str(uuid4()),
            "user_id": user["user_id"],
            "email": user["email"],
            "filters": filters,
            "recommendations": recommendations.to_dict("records"),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
    )


def parse_birth_date(value) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return date(2000, 1, 1)
    return date(2000, 1, 1)


def calculate_age_from_birth_date(birth_date: date, today: date | None = None, *, minimum: int = 0) -> int:
    today = today or date.today()
    birthday_passed = (today.month, today.day) >= (birth_date.month, birth_date.day)
    age = today.year - birth_date.year - (0 if birthday_passed else 1)
    return max(minimum, age)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --green: #ef4444;
            --green-dark: #dc2626;
            --ink: #17202a;
            --muted: #64748b;
            --line: #e5e7eb;
            --panel: #ffffff;
            --soft: #fef2f2;
            --amber: #f59e0b;
            --rose: #e11d48;
        }
        .stApp {
            background: #ffffff;
            color: var(--ink);
        }
        section[data-testid="stSidebar"] {
            background: #fff7f7;
            border-right: 1px solid var(--line);
        }
        section[data-testid="stSidebar"] .stButton > button {
            justify-content: flex-start;
            background: transparent;
            border: 0;
            color: var(--ink);
            font-weight: 500;
            padding: .55rem .75rem;
        }
        section[data-testid="stSidebar"] .stButton > button:hover {
            background: #fef2f2;
            color: var(--green-dark);
        }
        .sidebar-active {
            background: #fef2f2;
            border-left: 4px solid var(--green);
            border-radius: 8px;
            color: var(--green-dark);
            font-weight: 800;
            padding: .55rem .75rem;
            margin-bottom: .25rem;
        }
        .sidebar-spacer {
            height: .25rem;
        }
        .sidebar-brand {
            font-size: 1.45rem;
            font-weight: 800;
            color: var(--green-dark);
            margin: .5rem 0 0;
        }
        .sidebar-subtitle {
            color: var(--muted);
            font-size: .86rem;
            margin-bottom: 1.25rem;
        }
        .hero {
            padding: 2rem 0 1.25rem;
        }
        .brand {
            font-size: 2.6rem;
            line-height: 1;
            font-weight: 800;
            color: var(--green-dark);
            letter-spacing: 0;
        }
        .subtle {
            color: var(--muted);
            font-size: 1rem;
        }
        .metric-card {
            border: 1px solid var(--line);
            background: #ffffff;
            border-radius: 8px;
            padding: 1rem;
            min-height: 118px;
        }
        .home-header {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 1rem;
            margin: .25rem 0 1.25rem;
        }
        .home-title {
            font-size: 1.75rem;
            line-height: 1.15;
            font-weight: 800;
            color: var(--ink);
            margin: 0;
        }
        .home-kicker {
            color: var(--muted);
            font-size: .95rem;
            margin-top: .25rem;
        }
        .dashboard-card {
            border: 1px solid var(--line);
            background: #ffffff;
            border-radius: 8px;
            padding: 1.05rem;
            box-sizing: border-box;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        .dashboard-card.top-card {
            height: 214px;
        }
        .dashboard-card.tall-card {
            height: 292px;
        }
        .home-row-gap {
            height: .55rem;
        }
        .dashboard-title {
            font-size: 1rem;
            font-weight: 800;
            margin-bottom: .85rem;
            min-height: 22px;
        }
        .weight-value {
            font-size: 2rem;
            font-weight: 850;
            line-height: 1.05;
        }
        .target-line {
            color: var(--muted);
            font-size: .9rem;
            margin-top: .45rem;
        }
        .activity-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            border-bottom: 1px solid #f1f5f9;
            padding: .58rem 0;
            min-height: 48px;
            box-sizing: border-box;
        }
        .activity-item:last-child {
            border-bottom: 0;
        }
        .activity-name {
            font-weight: 700;
            line-height: 1.2;
            max-width: 230px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .activity-time {
            color: var(--muted);
            font-size: .84rem;
            white-space: nowrap;
        }
        .macro-row {
            margin-bottom: .95rem;
        }
        .macro-meta {
            display: flex;
            justify-content: space-between;
            color: var(--muted);
            font-size: .86rem;
            margin-bottom: .28rem;
        }
        .progress-track {
            height: 9px;
            background: #f1f5f9;
            border-radius: 999px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: var(--green);
            border-radius: 999px;
        }
        .calorie-focus {
            display: flex;
            align-items: center;
            gap: 1.15rem;
            flex: 1;
        }
        .calorie-ring {
            width: 122px;
            height: 122px;
            border-radius: 999px;
            background: conic-gradient(var(--green) 0 75%, #fee2e2 75% 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }
        .calorie-ring-inner {
            width: 88px;
            height: 88px;
            border-radius: 999px;
            background: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            font-weight: 850;
            color: var(--ink);
            line-height: 1.05;
        }
        .home-action {
            display: inline-block;
            background: var(--green);
            color: #ffffff;
            border-radius: 8px;
            padding: .55rem .75rem;
            font-weight: 750;
            margin-top: .8rem;
            width: fit-content;
        }
        .home-action.bottom {
            margin-top: auto;
        }
        .metric-label {
            color: var(--muted);
            font-size: .86rem;
            margin-bottom: .35rem;
        }
        .metric-value {
            font-size: 1.7rem;
            font-weight: 800;
            line-height: 1.1;
        }
        .meal-card, .exercise-card {
            border: 1px solid var(--line);
            background: #ffffff;
            border-radius: 8px;
            padding: 1rem;
            height: 100%;
        }
        .exercise-card {
            height: 320px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            overflow: hidden;
        }
        .exercise-title {
            min-height: 46px;
            font-size: 1rem;
            line-height: 1.25;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .exercise-desc {
            color: var(--muted);
            font-size: .9rem;
            line-height: 1.45;
            margin-top: .55rem;
            height: 78px;
            display: -webkit-box;
            -webkit-line-clamp: 3;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .workout-program {
            border: 1px solid var(--line);
            background: #ffffff;
            border-radius: 8px;
            padding: 1rem;
            margin-top: 1rem;
            margin-bottom: 1.25rem;
        }
        .workout-program-title {
            font-weight: 800;
            font-size: 1.15rem;
            margin-bottom: .15rem;
        }
        .workout-number {
            width: 38px;
            height: 38px;
            border-radius: 8px;
            background: #fee2e2;
            color: var(--green-dark);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
        }
        .workout-dose {
            border: 1px solid #fecaca;
            background: #fef2f2;
            color: #991b1b;
            border-radius: 8px;
            padding: .55rem .65rem;
            text-align: center;
            font-weight: 750;
            font-size: .9rem;
            margin-top: .75rem;
            min-height: 54px;
        }
        .workout-card-row {
            margin-bottom: 1rem;
        }
        .meal-row {
            border: 1px solid var(--line);
            background: #ffffff;
            border-radius: 8px;
            padding: .85rem;
            margin-bottom: .75rem;
        }
        .meal-image {
            width: 84px;
            height: 84px;
            object-fit: cover;
            border-radius: 8px;
            border: 1px solid var(--line);
            background: #f8fafc;
        }
        .chip {
            display: inline-block;
            border: 1px solid #fecaca;
            background: #fef2f2;
            color: #991b1b;
            border-radius: 999px;
            padding: .18rem .55rem;
            font-size: .78rem;
            margin-right: .25rem;
            margin-bottom: .25rem;
        }
        .danger-chip {
            border-color: #fecdd3;
            background: #fff1f2;
            color: #9f1239;
        }
        .food-title, .exercise-title {
            font-weight: 750;
            font-size: 1.02rem;
            margin-bottom: .35rem;
        }
        .section-title {
            font-size: 1.45rem;
            font-weight: 800;
            margin: 1rem 0 .35rem;
        }
        .stButton > button {
            border-radius: 8px;
            border: 1px solid var(--green);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def sidebar() -> None:
    st.sidebar.markdown(
        """
        <div class="sidebar-brand">NutriFit</div>
        <div class="sidebar-subtitle">Healthy Living</div>
        """,
        unsafe_allow_html=True,
    )

    if st.session_state.authenticated:
        pages = ["Home", "Profile", "Calorie Calculator", "Meal Recommendation", "Workout Recommendation"]
        if current_role() == "admin":
            pages.append("Admin Data")
        labels = {
            "Home": "Home",
            "Profile": "Profile",
            "Calorie Calculator": "Hitung Kalori",
            "Meal Recommendation": "Rekomendasi Menu",
            "Workout Recommendation": "Rekomendasi Latihan",
            "Admin Data": "Admin Data",
        }
        for page in pages:
            label = labels[page]
            if page == st.session_state.page:
                st.sidebar.markdown(f'<div class="sidebar-active">{label}</div>', unsafe_allow_html=True)
                st.sidebar.markdown('<div class="sidebar-spacer"></div>', unsafe_allow_html=True)
                continue
            if st.sidebar.button(label, key=f"nav_{page}", use_container_width=True):
                st.session_state.page = page
                st.rerun()
        st.sidebar.write("")
        st.sidebar.caption(f"Role: {current_role()}")
        if st.sidebar.button("Logout", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.current_user = None
            st.session_state.page = "Login"
            st.session_state.nutrition = None
            st.session_state.profile = None
            st.rerun()
    else:
        if st.sidebar.button("Masuk", use_container_width=True):
            st.session_state.page = "Login"
            st.rerun()
        if st.sidebar.button("Daftar", use_container_width=True):
            st.session_state.page = "Register"
            st.rerun()


def auth_view() -> None:
    col_left, col_right = st.columns([1.05, 0.95], gap="large")

    with col_left:
        st.markdown('<div class="hero"><div class="brand">NutriFit</div>', unsafe_allow_html=True)
        st.markdown(
            '<p class="subtle">Track your nutrition, achieve your goals, and transform your lifestyle with personalized meal and workout planning.</p></div>',
            unsafe_allow_html=True,
        )
        st.image(
            "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?auto=format&fit=crop&w=1200&q=80",
            use_container_width=True,
        )

    with col_right:
        if st.session_state.page == "Register":
            register_form()
        else:
            login_form()


def register_form() -> None:
    st.subheader("Create Your Account")
    with st.form("register_form"):
        name = st.text_input("Full Name", placeholder="John Doe")
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password")
        confirm_password = st.text_input("Confirm Password", type="password")
        birth_date = st.date_input("Birth Date", value=date(2000, 12, 25), min_value=date(1940, 1, 1), max_value=date.today())
        gender = st.radio("Gender", ["Male", "Female"], horizontal=True)
        agree = st.checkbox("I agree to the Terms and Conditions")
        submitted = st.form_submit_button("Register", use_container_width=True)

    if submitted:
        st.session_state.users = migrate_users(load_users())
        if not name or not email or not password:
            st.error("Please complete all required fields.")
        elif password != confirm_password:
            st.error("Password confirmation does not match.")
        elif email in st.session_state.users:
            st.error("Email is already registered.")
        elif not agree:
            st.error("Please accept the Terms and Conditions.")
        else:
            st.session_state.users[email] = {
                "user_id": str(uuid4()),
                "name": name,
                "email": email,
                "password": hash_password(password),
                "role": "user",
                "birth_date": birth_date.isoformat(),
                "gender": gender,
                "profile": None,
                "nutrition": None,
            }
            save_users(st.session_state.users)
            st.session_state.authenticated = True
            st.session_state.current_user = email
            st.session_state.page = "Home"
            st.success("Account created successfully.")
            st.rerun()


def login_form() -> None:
    st.subheader("Welcome Back")
    st.caption("Please enter your details.")
    with st.form("login_form"):
        email = st.text_input("Email", placeholder="Enter your email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)

    if submitted:
        st.session_state.users = migrate_users(load_users())
        user = st.session_state.users.get(email)
        if user and verify_password(user, password):
            st.session_state.authenticated = True
            st.session_state.current_user = email
            st.session_state.page = "Home"
            restore_user_context(email)
            st.rerun()
        else:
            st.error("Invalid email or password. Use Register first for this prototype.")


def profile_view() -> None:
    user = current_user()
    if not user:
        st.error("Data pengguna tidak ditemukan.")
        return

    st.markdown('<div class="brand">Profile</div>', unsafe_allow_html=True)
    st.caption("Kelola informasi akun yang sedang digunakan.")

    email = st.session_state.current_user
    birth_date = parse_birth_date(user.get("birth_date", date(2000, 1, 1)))
    gender_options = {"Laki-laki": "Male", "Perempuan": "Female"}
    current_gender = user.get("gender", "Male")
    gender_labels = list(gender_options)
    gender_index = 0 if current_gender == "Male" else 1

    with st.form("profile_form"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Nama Lengkap", value=user.get("name", ""))
            st.text_input("Email", value=user.get("email", email), disabled=True)
            birth_date_value = st.date_input(
                "Tanggal Lahir",
                value=birth_date,
                min_value=date(1940, 1, 1),
                max_value=date.today(),
            )
        with col2:
            st.number_input(
                "Umur",
                value=calculate_age_from_birth_date(birth_date_value),
                min_value=0,
                max_value=120,
                disabled=True,
            )
            gender_label = st.radio("Jenis Kelamin", gender_labels, index=gender_index, horizontal=True)
            new_password = st.text_input("Password Baru", type="password", placeholder="Kosongkan jika tidak diganti")
            confirm_password = st.text_input("Konfirmasi Password Baru", type="password")

        submitted = st.form_submit_button("Simpan Perubahan", use_container_width=True)

    if submitted:
        if not name.strip():
            st.error("Nama lengkap wajib diisi.")
            return
        if new_password and new_password != confirm_password:
            st.error("Konfirmasi password baru tidak sesuai.")
            return

        users = migrate_users(load_users())
        saved_user = users.get(email)
        if not saved_user:
            st.error("Data pengguna tidak ditemukan.")
            return

        saved_user["name"] = name.strip()
        saved_user["birth_date"] = birth_date_value.isoformat()
        saved_user["gender"] = gender_options[gender_label]
        if new_password:
            saved_user["password"] = hash_password(new_password)
            saved_user.pop("password_hash", None)

        save_users(users)
        st.session_state.users = migrate_users(load_users())
        st.success("Profile berhasil diperbarui.")
        st.rerun()


def home_view(members: pd.DataFrame, foods: pd.DataFrame, exercises: pd.DataFrame) -> None:
    user = current_user() or {"name": "Member"}
    nutrition = st.session_state.nutrition
    profile = st.session_state.profile

    st.markdown(
        f"""
        <div class="home-header">
            <div>
                <div class="home-title">Halo, {html.escape(user.get("name", "Member"))}</div>
                <div class="home-kicker">Berikut ringkasan aktivitas dan nutrisi Anda hari ini.</div>
            </div>
            <span class="chip">{html.escape(user.get("role", "user")).title()}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    target_calories = nutrition.target_calories if nutrition else 0
    consumed_calories = round(target_calories * 0.75) if nutrition else 0
    calorie_percent = 75 if nutrition else 0

    top_left, top_right = st.columns([0.9, 1.1], gap="small")
    with top_left:
        show_weight_trend_card(user.get("user_id"))
    with top_right:
        latest_workout = "Latihan Dada (Gym)" if st.session_state.exercise_recommendations is not None else "Rekomendasi Latihan"
        latest_meal = "Menu sehat harian" if st.session_state.food_recommendations is not None else "Rekomendasi Menu"
        st.markdown(
            f"""
            <div class="dashboard-card top-card">
                <div class="dashboard-title">Aktivitas Terakhir</div>
                <div class="activity-item">
                    <div><div class="activity-name">{latest_workout}</div><div class="subtle">Program latihan</div></div>
                    <div class="activity-time">2 jam lalu</div>
                </div>
                <div class="activity-item">
                    <div><div class="activity-name">Hitung Kalori</div><div class="subtle">{nutrition.bmi_status if nutrition else "Belum dihitung"}</div></div>
                    <div class="activity-time">4 jam lalu</div>
                </div>
                <div class="activity-item">
                    <div><div class="activity-name">{latest_meal}</div><div class="subtle">Target {target_calories:,.0f} kcal</div></div>
                    <div class="activity-time">6 jam lalu</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div class="home-row-gap"></div>', unsafe_allow_html=True)
    bottom_left, bottom_mid, bottom_right = st.columns([1.05, 0.95, 0.9], gap="small")
    with bottom_left:
        carbs = nutrition.carbohydrate_g if nutrition else 0
        protein = nutrition.protein_g if nutrition else 0
        fat = nutrition.fat_g if nutrition else 0
        with st.container(border=True):
            st.markdown('<div class="dashboard-title">Rasio Makro Hari Ini</div>', unsafe_allow_html=True)
            macro_progress("Karbohidrat", round(carbs * .75), carbs, 75)
            macro_progress("Protein", round(protein * .54), protein, 54)
            macro_progress("Lemak", round(fat * .69), fat, 69)
    with bottom_mid:
        st.markdown(
            f"""
            <div class="dashboard-card tall-card">
                <div class="dashboard-title">Target Kalori Hari Ini</div>
                <div class="calorie-focus">
                    <div class="calorie-ring">
                        <div class="calorie-ring-inner">{consumed_calories:,.0f}<br><span style="font-size:.75rem;">kcal</span></div>
                    </div>
                    <div>
                        <div class="weight-value">{calorie_percent}%</div>
                        <div class="target-line">dari target harian</div>
                        <div class="target-line">Target: {target_calories:,.0f} kcal</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with bottom_right:
        st.markdown(
            """
            <div class="dashboard-card tall-card">
                <div class="dashboard-title">Fakta Kesehatan Hari Ini</div>
                <p class="subtle" style="font-size:1.05rem; line-height:1.55;">Minum air sebelum makan dapat membantu mengontrol nafsu makan dan mendukung hidrasi harian.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )


def show_weight_trend_card(user_id: str | None) -> None:
    trend_data = weight_trend_data(user_id)

    with st.container(border=True):
        st.markdown('<div class="dashboard-title">Tren Berat Badan</div>', unsafe_allow_html=True)
        if trend_data.empty:
            st.caption("Lengkapi hitung kalori minimal satu kali untuk mulai melihat tren.")
            return

        st.altair_chart(weight_trend_chart(trend_data), use_container_width=True)


def weight_trend_chart(trend_data: pd.DataFrame) -> alt.Chart:
    base = alt.Chart(trend_data).encode(
        x=alt.X("Tanggal:T", title="Tanggal"),
        y=alt.Y("Berat (kg):Q", title="Berat (kg)", scale=alt.Scale(zero=False)),
        tooltip=[
            alt.Tooltip("Tanggal:T", title="Tanggal", format="%d %b %Y %H:%M"),
            alt.Tooltip("Berat (kg):Q", title="Berat", format=".1f"),
        ],
    )
    line = base.mark_line(color="#ef4444", strokeWidth=3)
    points = base.mark_circle(color="#ef4444", size=78, opacity=0.95)
    return (line + points).properties(height=158)


def weight_trend_data(user_id: str | None) -> pd.DataFrame:
    if not user_id:
        return pd.DataFrame(columns=["Tanggal", "Berat (kg)"])

    rows = []
    for record in load_records(CALORIE_DB_PATH):
        if record.get("user_id") != user_id:
            continue

        profile = record.get("profile") or {}
        weight = profile.get("weight_kg")
        created_at = record.get("created_at")
        if weight is None or not created_at:
            continue

        try:
            timestamp = datetime.fromisoformat(str(created_at))
            weight_value = float(weight)
        except (TypeError, ValueError):
            continue

        rows.append({"Tanggal": timestamp, "Berat (kg)": weight_value})

    return pd.DataFrame(rows).sort_values("Tanggal")


def macro_progress(label: str, current: int | float, target: int | float, percent: int) -> None:
    target_display = f"{target:,.0f}" if target else "0"
    current_display = f"{current:,.0f}" if current else "0"
    st.caption(f"{label} | {current_display}g / {target_display}g")
    st.progress(max(0, min(percent, 100)) / 100)


def calorie_view(members: pd.DataFrame) -> None:
    st.markdown('<div class="brand">Kalkulator Nutrisi</div>', unsafe_allow_html=True)
    st.caption("Masukkan data fisik dan gaya hidup Anda untuk mendapatkan rekomendasi kalori dan makronutrisi harian.")

    user = st.session_state.users.get(st.session_state.current_user, {})
    default_gender = user.get("gender", "Male")
    birth_date = parse_birth_date(user.get("birth_date", date(2000, 1, 1)))
    age = calculate_age_from_birth_date(birth_date, minimum=13)
    activity_options = {"Ringan": "Low", "Sedang": "Medium", "Tinggi": "High", "Sangat Tinggi": "Very High"}
    experience_options = {"Pemula": "Beginner", "Menengah": "Intermediate", "Ahli": "Expert"}
    goal_options = {
        "Menurunkan Berat": "Lose Weight",
        "Menjaga Berat": "Maintain Weight",
        "Menaikkan Berat": "Gain Weight",
    }

    with st.form("calorie_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            weight = st.number_input("Berat (kg)", min_value=30.0, max_value=250.0, value=70.0, step=0.5)
        with col2:
            height = st.number_input("Tinggi (cm)", min_value=120.0, max_value=230.0, value=175.0, step=0.5)
            activity_label = st.selectbox("Tingkat Aktivitas", list(activity_options), index=1)
        with col3:
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
        persist_user_profile(st.session_state.profile, nutrition)
        st.success("Profil nutrisi berhasil dihitung.")

    if st.session_state.nutrition:
        show_nutrition_result(st.session_state.nutrition, st.session_state.profile)
    show_calorie_transactions()


def show_nutrition_result(nutrition, profile) -> None:
    bmi_status_map = {
        "Underweight": "Berat Badan Kurang",
        "Normal": "Normal",
        "Overweight": "Berat Badan Berlebih",
        "Obese": "Obesitas",
    }
    st.markdown('<div class="section-title">Ringkasan Kesehatan</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    for col, (label, value) in zip(
        cols,
        [
            ("BMI", f"{nutrition.bmi} - {bmi_status_map.get(nutrition.bmi_status, nutrition.bmi_status)}"),
            ("BMR", f"{nutrition.bmr:,.0f} kcal"),
            ("TDEE", f"{nutrition.tdee:,.0f} kcal"),
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
            ("Target Kalori", f"{nutrition.target_calories:,.0f} kcal/hari"),
            ("Karbohidrat", f"{nutrition.carbohydrate_g:,.0f} g"),
            ("Protein", f"{nutrition.protein_g:,.0f} g"),
            ("Lemak", f"{nutrition.fat_g:,.0f} g"),
        ],
    ):
        with col:
            metric_card(label, value)
    st.caption(f"Segmen pengguna: Cluster {profile['user_cluster']}")


def show_calorie_transactions() -> None:
    user = current_user()
    user_id = user.get("user_id")
    records = [
        record
        for record in load_records(CALORIE_DB_PATH)
        if record.get("user_id") == user_id
    ]
    records = sorted(records, key=lambda record: record.get("created_at", ""), reverse=True)

    st.markdown('<div class="section-title">Transaction Calorie Records</div>', unsafe_allow_html=True)
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
        row_cols[3].write(f"{format_number(nutrition.get('target_calories'))} kcal")
        row_cols[4].write(f"{format_number(nutrition.get('protein_g'))} g")
        row_cols[5].write(goal_label(profile.get("fitness_goal")))
        if row_cols[6].button("Hapus", key=f"delete_calorie_{record.get('id')}", use_container_width=True):
            delete_record(CALORIE_DB_PATH, record.get("id"))
            sync_current_nutrition_from_records(user_id)
            st.success("Transaksi kalori berhasil dihapus.")
            st.rerun()


def format_record_datetime(value) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return parsed.strftime("%d %b %Y %H:%M")


def format_number(value) -> str:
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
    labels = {
        "Lose Weight": "Turun",
        "Maintain Weight": "Jaga",
        "Gain Weight": "Naik",
    }
    return labels.get(value or "", value or "-")


def sync_current_nutrition_from_records(user_id: str | None) -> None:
    email = st.session_state.current_user
    if not email or not user_id:
        return

    latest_record = latest_user_record(CALORIE_DB_PATH, user_id)
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


def meal_view(foods: pd.DataFrame) -> None:
    st.markdown('<div class="brand">Rekomendasi Menu</div>', unsafe_allow_html=True)
    st.caption("Buat menu harian berdasarkan target kalori dan preferensi makanan Anda.")

    if not ensure_nutrition_ready():
        return

    nutrition = st.session_state.nutrition
    show_compact_targets(nutrition)

    food_options = sorted(foods["name"].dropna().astype(str).unique().tolist())
    default_foods = [name for name in ["Ayam goreng", "Nasi", "Telur ayam"] if name in food_options]

    col1, col2 = st.columns([0.7, 0.3])
    with col1:
        selected_foods = st.multiselect(
            "Preferensi Makanan",
            options=food_options,
            default=default_foods,
            placeholder="Pilih satu atau beberapa makanan",
        )
    with col2:
        st.write("")
        generate = st.button("Buat Menu", use_container_width=True)

    preference = " ".join(selected_foods) if selected_foods else "balanced protein carbohydrate vegetable"

    if generate or st.session_state.food_recommendations is None:
        st.session_state.excluded_food_ids = []
        st.session_state.food_recommendations = recommend_foods(foods, nutrition, preference)
        persist_meal_recommendation(st.session_state.food_recommendations, selected_foods)

    display_meals(foods, preference)


def display_meals(foods: pd.DataFrame, preference: str) -> None:
    recommendations = st.session_state.food_recommendations or {}
    for meal_slot, items in recommendations.items():
        slot_label = meal_slot_label(meal_slot)
        st.markdown(f"### {slot_label}")
        if not items:
            st.warning(f"Belum ada kandidat menu yang cocok untuk {slot_label}.")
            continue

        for idx, item in enumerate(items):
            with st.container(border=True):
                image_col, detail_col, action_col = st.columns([0.16, 0.64, 0.20], vertical_alignment="center")
                with image_col:
                    image = item.get("image")
                    if isinstance(image, str) and image.startswith("http"):
                        st.image(image, width=84)
                    else:
                        st.markdown('<div class="meal-image"></div>', unsafe_allow_html=True)
                with detail_col:
                    st.markdown(
                        f"""
                        <div class="food-title">{html.escape(str(item['name']))}</div>
                        <span class="chip">Cluster {html.escape(str(item['Food_Cluster']))}</span>
                        <span class="chip">{item['target_calories']} kcal</span>
                        <p class="subtle">Porsi: {item['portion_gram']} g | Protein: {item['proteins']:.1f} g | Lemak: {item['fat']:.1f} g | Karbohidrat: {item['carbohydrate']:.1f} g</p>
                        """,
                        unsafe_allow_html=True,
                    )
                with action_col:
                    if st.button("Tukar", key=f"swap_{meal_slot}_{item['id']}", use_container_width=True):
                        replacement = swap_food(foods, item, item["target_calories"], preference)
                        if replacement:
                            replacement["is_swapped"] = True
                            st.session_state.excluded_food_ids.append(item["id"])
                            items[idx] = replacement
                            persist_meal_recommendation(st.session_state.food_recommendations, preference.split())
                            st.rerun()
                        st.warning("Belum ada menu pengganti yang cocok.")


def meal_slot_label(meal_slot: str) -> str:
    labels = {
        "Breakfast": "Sarapan",
        "Lunch": "Makan Siang",
        "Snack": "Camilan",
        "Dinner": "Makan Malam",
    }
    return labels.get(meal_slot, meal_slot)


def workout_view(exercises: pd.DataFrame) -> None:
    st.markdown('<div class="brand">Rekomendasi Latihan Gym</div>', unsafe_allow_html=True)
    st.caption("Pilih target otot dan dapatkan program latihan terstruktur yang disesuaikan dengan tujuan Anda.")

    if not ensure_nutrition_ready():
        return

    profile = st.session_state.profile
    body_parts = ["Any"] + sorted(exercises["BodyPart"].dropna().unique().tolist())
    workout_types = ["Any"] + sorted(exercises["Type"].dropna().unique().tolist())
    equipment = ["Any"] + sorted(exercises["Equipment"].dropna().unique().tolist())

    cols = st.columns(4)
    with cols[0]:
        body_part = st.selectbox("Target Otot", body_parts, index=body_parts.index("Chest") if "Chest" in body_parts else 0)
    with cols[1]:
        workout_type = st.selectbox("Jenis Latihan", workout_types, index=workout_types.index("Strength") if "Strength" in workout_types else 0)
    with cols[2]:
        equipment_preference = st.selectbox("Alat", equipment)
    with cols[3]:
        limit = st.slider("Jumlah Latihan", min_value=3, max_value=8, value=5)

    if st.button("Generate Latihan", use_container_width=True) or st.session_state.exercise_recommendations is None:
        st.session_state.exercise_recommendations = recommend_exercises(
            exercises,
            body_part=body_part,
            workout_type=workout_type,
            equipment_preference=equipment_preference,
            experience_level=profile["experience_level"],
            fitness_goal=profile["fitness_goal"],
            limit=limit,
        )
        persist_workout_recommendation(
            st.session_state.exercise_recommendations,
            {
                "body_part": body_part,
                "workout_type": workout_type,
                "equipment_preference": equipment_preference,
                "experience_level": profile["experience_level"],
                "fitness_goal": profile["fitness_goal"],
                "limit": limit,
            },
        )

    display_workouts(st.session_state.exercise_recommendations)


def display_workouts(recommendations: pd.DataFrame | None) -> None:
    if recommendations is None or recommendations.empty:
        st.info("No workout recommendations yet.")
        return

    body_part = recommendations.iloc[0]["BodyPart"] if "BodyPart" in recommendations else "Selected Muscle"
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
                st.markdown(
                    f"""
                    <div class="exercise-card">
                        <div>
                            <div class="workout-number">{number}</div>
                            <div class="exercise-title" style="margin-top:.75rem;">{html.escape(str(row['Title']))}</div>
                            <span class="chip">{html.escape(str(row['BodyPart']))}</span>
                            <span class="chip">{html.escape(str(row['Equipment']))}</span>
                            <span class="chip">{html.escape(str(row['Level']))}</span>
                            <div class="exercise-desc">{html.escape(str(row['Desc']))}</div>
                        </div>
                        <div class="workout-dose">
                            {row['sets']} sets x {row['reps']} reps<br>
                            Rest {row['rest_seconds']}s
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        st.markdown('<div class="workout-card-row"></div>', unsafe_allow_html=True)


def admin_view(members: pd.DataFrame, foods: pd.DataFrame, exercises: pd.DataFrame) -> None:
    if current_role() != "admin":
        st.error("Admin page is only available for admin users.")
        return

    st.markdown('<div class="brand">Admin Data</div>', unsafe_allow_html=True)
    st.caption("Inspect registered users, gym member data, food data, and workout data.")

    tab_users, tab_calorie, tab_meal, tab_workout, tab_performance, tab_members, tab_food, tab_exercise = st.tabs(
        [
            "Registered Users",
            "Calorie Data",
            "Meal Data",
            "Workout Data",
            "Performa Model",
            "Gym Members",
            "Food Dataset",
            "Workout Dataset",
        ]
    )
    with tab_users:
        admin_users_tab()
    with tab_calorie:
        admin_records_tab(CALORIE_DB_PATH, "Calorie")
    with tab_meal:
        admin_records_tab(MEAL_DB_PATH, "Meal recommendation")
    with tab_workout:
        admin_records_tab(WORKOUT_DB_PATH, "Workout recommendation")
    with tab_performance:
        admin_model_performance_tab(members, foods, exercises)
    with tab_members:
        st.dataframe(members, use_container_width=True, height=420)
    with tab_food:
        admin_food_dataset_tab(foods)
    with tab_exercise:
        admin_exercise_dataset_tab(exercises)


def admin_users_tab() -> None:
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
                "has_calorie_data": bool(latest_user_record(CALORIE_DB_PATH, user.get("user_id"))),
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
        st.info("No non-admin user can be deleted right now.")
        return

    with st.form("delete_user_form"):
        email = st.selectbox("Delete registered user", deletable_emails)
        submitted = st.form_submit_button("Delete User and Related Data", use_container_width=True)
    if submitted:
        delete_user_and_related_data(email)
        st.success(f"Deleted user and related data: {email}")
        st.rerun()


def admin_records_tab(path: Path, label: str) -> None:
    records = load_records(path)
    if records:
        st.dataframe(pd.DataFrame([summarize_record(record) for record in records]), use_container_width=True, height=360)
    else:
        st.info(f"No {label.lower()} records yet.")
        return

    record_options = {
        f"{record.get('created_at', 'no-date')} | {record.get('email', '-')} | {record.get('id')}": record.get("id")
        for record in records
    }
    with st.form(f"delete_{path.stem}_form"):
        selected = st.selectbox(f"Delete {label} record", list(record_options.keys()))
        submitted = st.form_submit_button(f"Delete {label}", use_container_width=True)
    if submitted:
        delete_record(path, record_options[selected])
        st.success(f"Deleted {label.lower()} record.")
        st.rerun()


def admin_model_performance_tab(members: pd.DataFrame, foods: pd.DataFrame, exercises: pd.DataFrame) -> None:
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
        cols[3].metric("Jumlah Cluster", payload["n_clusters"])
        silhouette = payload["silhouette_score"]
        cols[4].metric("Silhouette", "-" if silhouette is None else f"{silhouette:.3f}")

        metric_cols = st.columns([0.35, 0.65])
        metric_cols[0].metric(payload["cost_label"], f"{payload['cost']:,.3f}")
        metric_cols[1].dataframe(payload["counts"], use_container_width=True, hide_index=True)
        st.divider()


def admin_food_dataset_tab(foods: pd.DataFrame) -> None:
    st.dataframe(
        foods[["id", "name", "calories", "proteins", "fat", "carbohydrate", "Food_Cluster"]],
        use_container_width=True,
        height=300,
    )
    if not using_sql():
        st.info("CRUD dataset makanan membutuhkan database SQL aktif.")
        return

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
    exercises = ensure_exercise_ids(exercises)
    visible_columns = ["Program_ID", "Title", "Type", "BodyPart", "Equipment", "Level", "Exercise_Cluster"]
    st.dataframe(exercises[visible_columns], use_container_width=True, height=300)
    if not using_sql():
        st.info("CRUD dataset latihan membutuhkan database SQL aktif.")
        return

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
    exercises = exercises.copy()
    if "Program_ID" not in exercises.columns:
        exercises.insert(0, "Program_ID", exercises.index.astype(int))
    return exercises


def next_numeric_id(values: list[int], start: int = 1) -> int:
    return (max(values) + 1) if values else start


def safe_float(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if pd.isna(number):
        return 0.0
    return number


def upsert_food_record(record: dict) -> None:
    store = SQLStore()
    columns = ["id", "calories", "proteins", "fat", "carbohydrate", "name", "image"]
    upsert_dataset_record(store, "food_nutrition", "id", columns, record)


def upsert_exercise_record(record: dict) -> None:
    store = SQLStore()
    columns = ["program_id", "title", "description", "type", "body_part", "equipment", "level", "rating", "rating_desc"]
    upsert_dataset_record(store, "training_program", "program_id", columns, record)


def upsert_dataset_record(store: SQLStore, table: str, primary_key: str, columns: list[str], record: dict) -> None:
    placeholders = ", ".join([store.placeholder()] * len(columns))
    updates = ", ".join(dataset_update_clause(store.driver, columns, primary_key))
    if store.driver == "mysql":
        sql = f"""
            INSERT INTO {table} ({", ".join(columns)})
            VALUES ({placeholders})
            ON DUPLICATE KEY UPDATE {updates}
        """
    else:
        sql = f"""
            INSERT INTO {table} ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT ({primary_key}) DO UPDATE SET {updates}
        """
    with store.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(record.get(column) for column in columns))


def dataset_update_clause(driver: str, columns: list[str], primary_key: str) -> list[str]:
    if driver == "mysql":
        return [f"{column}=VALUES({column})" for column in columns if column != primary_key]
    return [f"{column}=EXCLUDED.{column}" for column in columns if column != primary_key]


def delete_dataset_record(table: str, primary_key: str, record_id: int) -> None:
    store = SQLStore()
    with store.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {table} WHERE {primary_key} = {store.placeholder()}", (record_id,))


def refresh_datasets_after_admin_change(message: str) -> None:
    get_data.clear()
    st.session_state.food_recommendations = None
    st.session_state.exercise_recommendations = None
    st.success(message)
    st.rerun()


def summarize_record(record: dict) -> dict:
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
    return summary


def ensure_nutrition_ready() -> bool:
    if st.session_state.nutrition is None:
        st.info("Silakan hitung target nutrisi Anda terlebih dahulu.")
        if st.button("Buka Kalkulator Kalori"):
            st.session_state.page = "Calorie Calculator"
            st.rerun()
        return False
    return True


def show_compact_targets(nutrition) -> None:
    cols = st.columns(4)
    for col, (label, value) in zip(
        cols,
        [
            ("Target Kalori", f"{nutrition.target_calories:,.0f} kcal"),
            ("Karbohidrat", f"{nutrition.carbohydrate_g:,.0f} g"),
            ("Protein", f"{nutrition.protein_g:,.0f} g"),
            ("Lemak", f"{nutrition.fat_g:,.0f} g"),
        ],
    ):
        with col:
            metric_card(label, value)


def metric_card(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    init_state()
    inject_css()
    members, foods, exercises = get_data()
    sidebar()

    if not st.session_state.authenticated:
        auth_view()
        return

    page = st.session_state.page
    if page == "Home":
        home_view(members, foods, exercises)
    elif page == "Profile":
        profile_view()
    elif page == "Calorie Calculator":
        calorie_view(members)
    elif page == "Meal Recommendation":
        meal_view(foods)
    elif page == "Workout Recommendation":
        workout_view(exercises)
    elif page == "Admin Data":
        admin_view(members, foods, exercises)


if __name__ == "__main__":
    main()
