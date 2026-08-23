"""Metrik evaluasi rekomendasi berbasis peringkat (Top-N) untuk Content-Based Filtering.

Dipakai notebook pengujian, BUKAN oleh aplikasi saat melayani pengguna. Berisi
MAP (Mean Average Precision), NDCG (Normalized Discounted Cumulative Gain), dan
pembanding peringkat acak. Keduanya memakai relevansi biner.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _siapkan(relevance, k: int | None) -> tuple[np.ndarray, int]:
    """Ubah daftar relevansi terurut jadi array 0/1 dan tentukan panjang Top-K efektif."""
    urutan = np.asarray(relevance, dtype=bool).astype(float)
    batas = len(urutan) if k is None else min(int(k), len(urutan))
    return urutan, batas


def average_precision_at_k(relevance, k: int | None = None, *, total_relevant: int | None = None) -> float:
    """Average Precision@K untuk SATU kueri.

        AP@K = (1 / min(R, K)) * sum P@i * rel_i

    Pembaginya min(R, K), bukan K, supaya kueri yang item relevannya lebih sedikit
    daripada K masih bisa mencapai 1,0 pada susunan sempurna.
    """
    urutan, batas = _siapkan(relevance, k)
    if batas == 0:
        return 0.0
    R = int(urutan.sum()) if total_relevant is None else int(total_relevant)
    if R == 0:
        return 0.0

    ditemukan = 0
    total = 0.0
    for i in range(batas):
        if urutan[i]:
            ditemukan += 1
            total += ditemukan / (i + 1)          # P@i pada saat item relevan ditemukan
    return float(total / min(R, batas))


def dcg_at_k(relevance, k: int | None = None) -> float:
    """Discounted Cumulative Gain@K dengan keuntungan biner."""
    urutan, batas = _siapkan(relevance, k)
    if batas == 0:
        return 0.0
    peringkat = np.arange(1, batas + 1)
    return float((urutan[:batas] / np.log2(peringkat + 1)).sum())


def ndcg_at_k(relevance, k: int | None = None, *, total_relevant: int | None = None) -> float:
    """NDCG@K untuk SATU kueri: DCG dibagi DCG susunan sempurna.

    Susunan sempurna adalah daftar yang seluruh item relevannya berada di
    peringkat teratas -- sebanyak min(R, K) buah.
    """
    urutan, batas = _siapkan(relevance, k)
    if batas == 0:
        return 0.0
    R = int(urutan.sum()) if total_relevant is None else int(total_relevant)
    ideal = min(R, batas)
    if ideal == 0:
        return 0.0
    idcg = float((1.0 / np.log2(np.arange(1, ideal + 1) + 1)).sum())
    return float(dcg_at_k(urutan, batas) / idcg) if idcg else 0.0


def mean_average_precision(relevances, k: int | None = None) -> float:
    """MAP: rata-rata Average Precision@K atas seluruh kueri."""
    nilai = [average_precision_at_k(r, k) for r in relevances]
    return float(np.mean(nilai)) if nilai else 0.0


def mean_ndcg(relevances, k: int | None = None) -> float:
    """Rata-rata NDCG@K atas seluruh kueri."""
    nilai = [ndcg_at_k(r, k) for r in relevances]
    return float(np.mean(nilai)) if nilai else 0.0


def ranking_report(relevance_per_query: dict, k_values=(5, 10)) -> pd.DataFrame:
    """Tabel AP@K dan NDCG@K per kueri, plus jumlah item relevan yang tersedia.

    `relevance_per_query` memetakan nama kueri ke penanda relevansi dalam urutan
    peringkat, mis. `{"Ayam": array([True, True, False, ...]), ...}`.
    """
    baris = []
    for nama, penanda in relevance_per_query.items():
        urutan = np.asarray(penanda, dtype=bool)
        catatan = {"Kueri": nama, "Item relevan": int(urutan.sum())}
        for k in k_values:
            catatan[f"AP@{k}"] = round(average_precision_at_k(urutan, k), 4)
            catatan[f"NDCG@{k}"] = round(ndcg_at_k(urutan, k), 4)
        baris.append(catatan)
    return pd.DataFrame(baris)


def random_baseline(relevance_per_query: dict, k_values=(5, 10), *, runs: int = 200,
                    random_state: int = 42) -> pd.DataFrame:
    """MAP dan NDCG yang dicapai peringkat ACAK pada kueri dan korpus yang sama.

    Angka MAP/NDCG tidak punya arti tanpa pembanding: nilai 0,4 bisa berarti
    bagus atau buruk tergantung berapa banyak item relevan yang tersedia. Di
    sini penanda relevansi yang SAMA diacak urutannya berulang kali, sehingga
    pembandingnya berbagi persis ukuran korpus dan sebaran relevansinya.
    """
    rng = np.random.default_rng(random_state)
    kumpulan = {k: {"MAP": [], "NDCG": []} for k in k_values}
    for _ in range(runs):
        diacak = [rng.permutation(np.asarray(r, dtype=bool)) for r in relevance_per_query.values()]
        for k in k_values:
            kumpulan[k]["MAP"].append(mean_average_precision(diacak, k))
            kumpulan[k]["NDCG"].append(mean_ndcg(diacak, k))
    return pd.DataFrame([
        {"K": k,
         "MAP acak": round(float(np.mean(kumpulan[k]["MAP"])), 4),
         "NDCG acak": round(float(np.mean(kumpulan[k]["NDCG"])), 4)}
        for k in k_values
    ])
