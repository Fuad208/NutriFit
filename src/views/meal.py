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
    carb_preference_options,
    food_categories_for_name,
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

    # Preferensi berupa pilihan kategori, bukan ketikan bebas: mencentang
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
        # Tujuan menentukan SUSUNAN peran gizi tiap slot, bukan sekadar besaran
        # kalorinya. Diambil dengan .get() karena record lama bisa belum memuat
        # kuncinya; meal_template() jatuh ke "Maintain Weight" bila begitu.
        profil = st.session_state.profile or {}
        st.session_state.food_recommendations = recommend_foods(
            foods,
            nutrition,
            categories=st.session_state.meal_categories,
            fitness_goal=profil.get("fitness_goal"),
        )
        st.session_state.meal_from_storage = False
        persist_meal_recommendation(
            st.session_state.food_recommendations,
            st.session_state.meal_categories,
        )

    # Menu hanya disusun setelah tombolnya ditekan, supaya pengguna tidak
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


def _render_kartu_preferensi(
    judul: str,
    pilihan: dict[str, tuple[str, ...]],
    terpilih: set[str],
    kunci_kartu: str,
    keterangan: str | None = None,
) -> list[str]:
    """Satu kartu pilihan kategori, tiga kolom per baris.

    `pilihan` memetakan label yang tampil ke satu atau lebih kategori dataset, supaya
    beberapa kategori bisa disodorkan sebagai satu pilihan. Kunci checkbox dirakit
    dari LABEL, bukan kategorinya, karena satu label bisa mewakili beberapa kategori.
    """
    hasil: list[str] = []
    with st.container(border=True, key=kunci_kartu):
        st.markdown(f'<div class="card-title">{judul}</div>', unsafe_allow_html=True)
        label_list = list(pilihan)
        for baris_awal in range(0, len(label_list), 3):
            baris = label_list[baris_awal : baris_awal + 3]
            kolom = st.columns(3)
            for kol, label in zip(kolom, baris):
                kategori = pilihan[label]
                with kol:
                    if st.checkbox(
                        label,
                        value=any(k in terpilih for k in kategori),
                        key=f"pref_{label}",
                    ):
                        hasil.extend(kategori)
            # Baris terakhir yang tidak penuh: sisa kolomnya dibiarkan kosong
            # supaya lebar tiap kotak tetap sama dengan baris di atasnya.
        if keterangan:
            st.caption(keterangan)
    return hasil


def render_protein_preference(foods: pd.DataFrame) -> list[str]:
    """Render dua kartu preferensi -- sumber protein dan sumber karbohidrat.

    Keduanya masuk ke satu daftar `meal_categories` yang sama, karena `_rank_foods()`
    menggabungkan kategori dengan OR lalu `_candidate_tiers()` yang memilah per peran
    gizi slot. Nilainya disimpan sebagai nama kategori dataset, bukan label tampilan.
    """
    protein = protein_preference_options(foods)
    karbo = carb_preference_options(foods)
    if not protein and not karbo:
        return []

    terpilih = set(st.session_state.get("meal_categories") or [])
    hasil: list[str] = []

    if protein:
        hasil += _render_kartu_preferensi(
            "Preferensi Sumber Protein", protein, terpilih, "card_protein_pref"
        )
    if karbo:
        hasil += _render_kartu_preferensi(
            "Preferensi Sumber Karbohidrat", karbo, terpilih, "card_carb_pref",
            "Kosongkan semua untuk membiarkan sistem memilih menu paling seimbang.",
        )

    # Satu kategori bisa disodorkan dua kali kalau kelak muncul di kedua daftar;
    # dedup sambil menjaga urutan supaya kuerinya tetap bisa ditebak.
    st.session_state.meal_categories = list(dict.fromkeys(hasil))
    return st.session_state.meal_categories


def render_quota_explainer(nutrition) -> None:
    """Panel penjelas asal angka kuota kalori tiap slot beserta rumus gramasinya."""
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

    Ditandai per tanggal supaya pencarian record hanya dilakukan sekali per hari per
    sesi, dan tetap dicoba lagi setelah tanggal berganti.
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


def gambar_terkini(item: dict, foods: pd.DataFrame | None) -> tuple[object, bool]:
    """Alamat gambar dan status tampilnya, diambil dari dataset yang SEDANG aktif.

    Rekomendasi tersimpan adalah salinan baris menu saat menu disusun. Salinan itu
    tetap dipakai untuk angka gizi dan gramasi supaya riwayat tidak berubah surut,
    tetapi gambar dibaca ulang dari dataset supaya perbaikan tautan oleh admin ikut
    terlihat. Snapshot dipakai sebagai cadangan bila barisnya sudah dihapus.
    """
    if foods is not None and "id" in getattr(foods, "columns", []):
        try:
            food_id = int(item.get("id"))
        except (TypeError, ValueError):
            food_id = None
        if food_id is not None:
            baris = foods[foods["id"] == food_id]
            if not baris.empty:
                terkini = baris.iloc[0]
                return terkini.get("image"), bool(terkini.get("Has_Image", True))
    return item.get("image"), bool(item.get("Has_Image", True))


def meal_image_html(item: dict, foods: pd.DataFrame | None = None) -> str:
    """Gambar menu, dengan gambar pengganti sebagai latar kotaknya.

    Foto aslinya ditumpuk di atas latar itu, sehingga tautan yang mati tidak
    menyisakan ikon gambar rusak. `foods` boleh dikosongkan; tanpa dataset, alamatnya
    dibaca apa adanya dari item yang dioper.
    """
    alamat, punya_gambar = gambar_terkini(item, foods)
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
            st.markdown(meal_image_html(item, foods), unsafe_allow_html=True)

        with detail_col:
            # SELURUH kategori yang dimiliki menu ini, bukan cuma yang menang
            # prioritas. "Keripik tempe" adalah kerupuk sekaligus olahan tempe,
            # dan menampilkan satu label saja membuat pengguna mengira sistem
            # salah menempatkannya.
            categories = food_categories_for_name(str(item.get("name") or ""))
            category_chips = "".join(
                f'<span class="chip">{html.escape(label)}</span>' for label in categories
            ) or f'<span class="chip">{html.escape(OTHER_CATEGORY)}</span>'
            st.markdown(
                f"""
                <div class="food-title">{html.escape(str(item['name']))}</div>
                {category_chips}
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
    """Kontrol tukar satu item menu, beserta pilihan kategori penggantinya."""
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
                fitness_goal=(st.session_state.profile or {}).get("fitness_goal"),
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
