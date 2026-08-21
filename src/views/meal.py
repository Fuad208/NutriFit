"""Halaman rekomendasi menu makanan."""

from __future__ import annotations

import html
import pandas as pd
import streamlit as st

from datetime import date

from src.database import MEAL_STORE
from src.recommender import (
    MEAL_DISTRIBUTION,
    OTHER_CATEGORY,
    SNACK_SLOT,
    available_food_categories,
    protein_preference_options,
    recommend_foods,
    slot_calorie_quota,
    swap_food,
)

from ..core.i18n import id_slot_makan
from ..core.progress import latest_record_today
from ..core.state import current_user, ensure_nutrition_ready, persist_meal_recommendation
from .home import show_compact_targets


def meal_view(foods: pd.DataFrame) -> None:
    """Halaman rekomendasi menu: pilih kategori bahan, susun menu harian, simpan, lalu tampilkan kartunya."""
    st.markdown('<div class="brand">Rekomendasi Menu</div>', unsafe_allow_html=True)
    st.caption("Buat menu harian berdasarkan target kalori dan preferensi makanan Anda.")

    if not ensure_nutrition_ready():
        return

    nutrition = st.session_state.nutrition
    show_compact_targets(nutrition)

    all_categories = available_food_categories(foods)
    snack_categories = available_food_categories(foods, meal_slot=SNACK_SLOT)

    # Pemulihan menu hari ini dijalankan SEBELUM widget pilihan kategori dirender.
    # Streamlit mengunci nilai widget pada `key` setelah render pertama, jadi
    # memulihkan sesudahnya membuat kategori yang tersimpan tidak pernah muncul
    # kembali di pilihannya walaupun menunya sendiri tampil.
    restore_today_menu(all_categories)

    # Dulu preferensi diketik bebas, sehingga user harus menebak kata kunci apa
    # yang ada di dataset. Sekarang berupa pilihan sumber protein -- mencentang
    # "Ayam" sudah mencakup SELURUH menu berbahan ayam (ayam goreng, ayam
    # ampela, ayam taliwang, dan seterusnya).
    selected_categories = render_protein_preference(foods)

    unavailable_for_snack = [
        label for label in (selected_categories or []) if label not in snack_categories
    ]
    if unavailable_for_snack:
        st.caption(
            f"Catatan: {', '.join(unavailable_for_snack)} tidak tersedia untuk slot "
            f"{id_slot_makan(SNACK_SLOT)} karena bukan makanan camilan. Slot itu akan "
            "diisi kategori camilan yang paling mendekati preferensi Anda."
        )

    generate = st.button("Buat Menu", use_container_width=True)

    if generate:
        st.session_state.excluded_food_ids = []
        st.session_state.meal_categories = list(selected_categories or [])
        st.session_state.food_recommendations = recommend_foods(
            foods,
            nutrition,
            categories=st.session_state.meal_categories,
        )
        st.session_state.meal_from_storage = False
        persist_meal_recommendation(
            st.session_state.food_recommendations,
            st.session_state.meal_categories,
        )

    # Hanya tampil setelah user menekan tombolnya. Sebelumnya menu langsung
    # dibuat begitu halaman dibuka, sehingga user mengira daftar itu sudah
    # disesuaikan dengan preferensinya padahal dia belum memasukkan apa pun.
    if st.session_state.food_recommendations is None:
        st.info(
            "Pilih preferensi makanan Anda (boleh dikosongkan), lalu tekan "
            "**Buat Menu** untuk melihat rekomendasi menu harian."
        )
        return

    if st.session_state.get("meal_from_storage"):
        st.caption(
            "Menampilkan menu yang sudah Anda buat hari ini, lengkap dengan "
            "centang \"sudah dimakan\". Tekan **Buat Menu** kalau ingin menyusun ulang."
        )

    render_quota_explainer(nutrition)
    display_meals(foods, snack_categories, all_categories)


def render_protein_preference(foods: pd.DataFrame) -> list[str]:
    """Kartu pilihan sumber protein, tiga kolom per baris.

    Hanya sumber protein yang ditawarkan. Karbohidrat dan pelengkap tidak ikut
    dipilih karena porsinya sudah ditentukan MEAL_TEMPLATE lewat klaster A/B/C --
    yang benar-benar menentukan rasa sebuah menu adalah lauknya.

    Nilainya disimpan di `meal_categories` sebagai nama kategori dataset, bukan
    label yang tampil, supaya recommend_foods tidak perlu tahu soal tampilan.
    """
    pilihan = protein_preference_options(foods)
    if not pilihan:
        return []

    terpilih = set(st.session_state.get("meal_categories") or [])
    hasil: list[str] = []

    with st.container(border=True, key="card_protein_pref"):
        st.markdown(
            '<div class="card-title">Preferensi Sumber Protein</div>',
            unsafe_allow_html=True,
        )
        label_list = list(pilihan)
        for baris_awal in range(0, len(label_list), 3):
            baris = label_list[baris_awal : baris_awal + 3]
            kolom = st.columns(3)
            for kol, label in zip(kolom, baris):
                kategori = pilihan[label]
                with kol:
                    if st.checkbox(
                        label,
                        value=kategori in terpilih,
                        key=f"pref_{kategori}",
                    ):
                        hasil.append(kategori)
            # Baris terakhir yang tidak penuh: sisa kolomnya dibiarkan kosong
            # supaya lebar tiap kotak tetap sama dengan baris di atasnya.

        st.caption(
            "Kosongkan semua untuk membiarkan sistem memilih menu paling seimbang."
        )

    st.session_state.meal_categories = hasil
    return hasil



def render_quota_explainer(nutrition) -> None:
    """Jelaskan dari mana angka kuota tiap slot berasal.

    Tanpa ini angka "500 kkal" pada judul slot terbaca seperti angka ajaib.
    Ditaruh di expander supaya tidak mengganggu alur utama halaman.
    """
    target = float(getattr(nutrition, "target_calories", 0) or 0)
    quotas = slot_calorie_quota(target)
    with st.expander("Bagaimana porsi tiap slot dihitung?"):
        rows = [
            {
                "Slot": id_slot_makan(slot),
                "Proporsi": f"{MEAL_DISTRIBUTION[slot]:.0%}",
                "Kuota Kalori": f"{quota:,.0f} kkal",
            }
            for slot, quota in quotas.items()
        ]
        rows.append(
            {
                "Slot": "Total",
                "Proporsi": "100%",
                "Kuota Kalori": f"{sum(quotas.values()):,.0f} kkal",
            }
        )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.markdown(
            "Kuota tiap slot adalah target kalori harian Anda dikalikan proporsi slot, "
            "sehingga jumlah keempat slot selalu sama dengan kebutuhan energi harian. "
            "Gramasi tiap menu dihitung dengan "
            "**porsi (g) = (kuota kalori item ÷ kalori per 100 g) × 100**, lalu diperiksa "
            "agar berada di rentang wajar 50–450 g. Menu yang porsinya di luar rentang itu "
            "dilewati dan sistem mengambil peringkat kemiripan berikutnya."
        )


def restore_today_menu(all_categories: list[str]) -> None:
    """Muat kembali menu HARI INI dari database ke session state.

    Session state hilang tiap kali halaman di-refresh atau user login ulang,
    sedangkan record menunya masih tersimpan. Tanpa pemulihan ini user harus
    menekan "Buat Menu" lagi untuk bisa melanjutkan -- dan menu baru itu
    menggantikan menu yang sedang dia jalani hari itu beserta centang
    "sudah dimakan"-nya.

    Ditandai per tanggal (`meal_restored_on`) supaya pencarian record hanya
    dilakukan sekali per hari per sesi, bukan tiap kali halaman dirender ulang
    (mis. tiap centang), dan tetap dicoba lagi setelah tanggal berganti.
    """
    if st.session_state.food_recommendations is not None:
        return

    today = date.today().isoformat()
    if st.session_state.get("meal_restored_on") == today:
        return
    st.session_state.meal_restored_on = today

    record = latest_record_today(MEAL_STORE, current_user().get("user_id"))
    recommendations = (record or {}).get("recommendations")
    if not isinstance(recommendations, dict) or not recommendations:
        return

    st.session_state.food_recommendations = recommendations
    st.session_state.excluded_food_ids = []
    st.session_state.meal_from_storage = True

    # `preference` disimpan sebagai daftar label kategori (lihat
    # persist_meal_recommendation). Record lama menyimpan kata kunci bebas, jadi
    # yang bukan nama kategori sekarang diabaikan saja -- menunya tetap tampil,
    # hanya pilihan filternya yang kembali kosong.
    preference = record.get("preference")
    if isinstance(preference, str):
        preference = preference.split()
    if isinstance(preference, list):
        st.session_state.meal_categories = [
            str(label) for label in preference if str(label) in all_categories
        ]


def display_meals(
    foods: pd.DataFrame,
    snack_categories: list[str],
    all_categories: list[str],
) -> None:
    """Render menu per slot makan (sarapan, makan siang, camilan, makan malam) beserta totalnya."""
    recommendations = st.session_state.food_recommendations or {}
    selected_categories = st.session_state.get("meal_categories") or []
    displayed_food_ids = {
        int(item["id"])
        for slot_items in recommendations.values()
        for item in slot_items
        if item.get("id") is not None
    }

    for meal_slot, items in recommendations.items():
        st.markdown(slot_heading_html(meal_slot, items), unsafe_allow_html=True)
        if not items:
            st.warning(f"Belum ada kandidat menu yang cocok untuk {id_slot_makan(meal_slot)}.")
            continue

        slot_options = snack_categories if meal_slot == SNACK_SLOT else all_categories
        for idx, item in enumerate(items):
            render_meal_card(
                foods,
                meal_slot,
                idx,
                item,
                items,
                slot_options,
                selected_categories,
                displayed_food_ids,
            )


def slot_heading_html(meal_slot: str, items: list[dict]) -> str:
    """Judul slot lengkap dengan proporsi dan kuota kalorinya."""
    label = id_slot_makan(meal_slot)
    ratio = MEAL_DISTRIBUTION.get(meal_slot)
    quota = items[0].get("slot_quota_calories") if items else None
    parts = [f'<span class="slot-name">{html.escape(label)}</span>']
    if ratio is not None:
        parts.append(f'<span class="chip">{ratio:.0%} dari target harian</span>')
    if quota:
        parts.append(f'<span class="chip">{float(quota):,.0f} kkal</span>')
    if items and len(items) > 1:
        parts.append(f'<span class="chip">{len(items)} item</span>')
    return f'<div class="slot-head">{"".join(parts)}</div>'


def meal_image_html(item: dict) -> str:
    """Gambar menu, dengan gambar pengganti sebagai dasarnya.

    Gambar pengganti bukan cadangan yang dipasang belakangan melainkan LATAR
    dari kotaknya, dan foto aslinya ditumpuk di atasnya. Dengan begitu tautan
    yang mati tidak menyisakan ikon gambar rusak: `<img>` yang gagal dimuat
    tidak menggambar apa pun, sehingga latarnya yang terlihat. Tidak ada
    JavaScript yang terlibat, jadi tidak bergantung pada sanitizer Streamlit.

    Ketersediaan gambar juga tidak lagi menentukan sebuah menu boleh muncul
    atau tidak, jadi kartu ini harus tetap rapi tanpa foto sama sekali.
    """
    alamat = item.get("image")
    punya_gambar = bool(item.get("Has_Image", True))
    layak = punya_gambar and isinstance(alamat, str) and alamat.startswith(("http://", "https://"))
    if not layak:
        return '<div class="meal-image" aria-hidden="true"></div>'
    return (
        '<div class="meal-image">'
        f'<img src="{html.escape(alamat, quote=True)}" alt="" loading="lazy">'
        "</div>"
    )


def render_meal_card(
    foods: pd.DataFrame,
    meal_slot: str,
    idx: int,
    item: dict,
    items: list[dict],
    slot_options: list[str],
    selected_categories: list[str],
    displayed_food_ids: set[int],
) -> None:
    """Render satu kartu menu: gambar, gizi per porsi, dan tombol ganti item."""
    with st.container(border=True):
        image_col, detail_col, action_col = st.columns([0.16, 0.64, 0.20], vertical_alignment="center")
        with image_col:
            st.markdown(meal_image_html(item), unsafe_allow_html=True)

        with detail_col:
            category = str(item.get("Food_Category") or OTHER_CATEGORY)
            st.markdown(
                f"""
                <div class="food-title">{html.escape(str(item['name']))}</div>
                <span class="chip">{html.escape(category)}</span>
                <span class="chip">Klaster {html.escape(str(item['Food_Cluster']))}</span>
                <span class="chip">{item['target_calories']} kkal</span>
                <p class="subtle">Porsi: {item['portion_gram']} g | Protein: {item['proteins']:.1f} g | Lemak: {item['fat']:.1f} g | Karbohidrat: {item['carbohydrate']:.1f} g</p>
                """,
                unsafe_allow_html=True,
            )
            if selected_categories and not item.get("category_match", True):
                st.caption(
                    "Di luar kategori pilihan Anda — tidak ada menu dari kategori itu "
                    "yang porsinya masuk rentang wajar untuk slot ini."
                )

        with action_col:
            is_eaten = st.checkbox(
                "Sudah dimakan",
                value=bool(item.get("is_eaten", False)),
                key=f"eaten_{meal_slot}_{item['id']}",
            )
            if is_eaten != bool(item.get("is_eaten", False)):
                item["is_eaten"] = is_eaten
                items[idx] = item
                persist_meal_recommendation(
                    st.session_state.food_recommendations,
                    st.session_state.get("meal_categories") or [],
                )
                st.rerun()

            render_swap_control(
                foods,
                meal_slot,
                idx,
                item,
                items,
                slot_options,
                selected_categories,
                displayed_food_ids,
            )


def render_swap_control(
    foods: pd.DataFrame,
    meal_slot: str,
    idx: int,
    item: dict,
    items: list[dict],
    slot_options: list[str],
    selected_categories: list[str],
    displayed_food_ids: set[int],
) -> None:
    """Tombol tukar beserta pilihan kategori penggantinya.

    Filter kategori yang sama dengan halaman rekomendasi juga berlaku di sini --
    itulah kenapa pilihannya dibawa ke dalam popover, bukan sekadar mewarisi
    filter halaman: user sering ingin mengganti SATU item dengan bahan lain
    tanpa menyusun ulang seluruh menu.
    """
    with st.popover("Tukar", use_container_width=True):
        st.markdown(f"**Ganti {item['name']}**")
        st.caption(
            f"Pengganti diambil dari klaster yang sama (Klaster {item['Food_Cluster']}) dan "
            f"porsinya dihitung ulang agar tetap {item['target_calories']} kkal, sehingga "
            "total kalori harian Anda tidak berubah."
        )
        # Sengaja DIBIARKAN KOSONG, tidak mewarisi filter halaman. Kotak yang
        # sudah terisi semua kategori saat dibuka terbaca seolah user pernah
        # memilihnya, padahal belum -- dan menghapusnya satu per satu lebih
        # merepotkan daripada menambahkan yang benar-benar diinginkan. Kosong
        # di sini berarti "semua kategori boleh".
        swap_categories = st.multiselect(
            "Kategori pengganti",
            slot_options,
            default=[],
            key=f"swapcat_{meal_slot}_{item['id']}",
            placeholder="Semua kategori — ketik untuk menyaring",
        )
        if st.button("Tukar Sekarang", key=f"swap_{meal_slot}_{item['id']}", use_container_width=True):
            excluded_food_ids = displayed_food_ids | set(st.session_state.excluded_food_ids)
            replacement = swap_food(
                foods,
                item,
                item["target_calories"],
                excluded_food_ids=excluded_food_ids,
                meal_slot=meal_slot,
                categories=swap_categories,
            )
            if replacement is None:
                st.warning("Belum ada menu pengganti yang cocok.")
                return

            replacement["is_swapped"] = True
            replacement["is_eaten"] = False
            st.session_state.excluded_food_ids.append(item["id"])
            items[idx] = replacement
            persist_meal_recommendation(
                st.session_state.food_recommendations,
                st.session_state.get("meal_categories") or [],
            )
            st.rerun()
