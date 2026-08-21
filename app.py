from __future__ import annotations

import streamlit as st

# Harus PALING ATAS, sebelum impor apa pun yang memakai argon2/psycopg.
# Mengubah "ModuleNotFoundError: No module named 'argon2'" -- yang menunjuk ke
# berkas yang sebenarnya tidak bermasalah -- menjadi instruksi cara menjalankan
# aplikasi lewat venv yang benar.
from src.preflight import pastikan_lingkungan

pastikan_lingkungan("app.py")

from src.core.data import get_data  # noqa: E402
from src.core.sidebar import sidebar
from src.core.state import init_state
from src.core.styles import inject_css
from src.views.auth import auth_view
from src.views.calorie import calorie_view
from src.views.home import home_view
from src.views.meal import meal_view
from src.views.profile import profile_view
from src.views.workout import workout_tutorial_view, workout_view


st.set_page_config(
    page_title="NutriFit",
    page_icon="N",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    """Titik masuk aplikasi pengguna: siapkan state, muat dataset, lalu render halaman aktif."""
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
    elif page == "Workout Tutorial":
        workout_tutorial_view()


if __name__ == "__main__":
    main()
