"""Uji metrik evaluasi: Metode Siku, jarak Gower, MAP, dan NDCG pada data buatan."""
import sys
from pathlib import Path

ROOT = Path(r"c:\Kuliah\Semester 8\Tugas Akhir\Coding\NutriFit")
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from src.recommender import (  # noqa: E402
    elbow_cluster_count,
    elbow_distances,
    elbow_table,
    gower_pairwise_distances,
    gower_silhouette,
    safe_calinski_harabasz,
)
from src.ranking_metrics import (  # noqa: E402
    average_precision_at_k,
    dcg_at_k,
    mean_average_precision,
    mean_ndcg,
    ndcg_at_k,
    random_baseline,
    ranking_report,
)

K_RANGE = list(range(2, 11))

print("== Metode Siku: kurva dengan siku yang sudah diketahui ==")
# Turun tajam sampai K=4, lalu nyaris datar. Sikunya jelas di 4.
kurva_tajam = [100.0, 50.0, 25.0, 24.0, 23.0, 22.0, 21.0, 20.0, 19.0]
siku = elbow_cluster_count(K_RANGE, kurva_tajam)
print(f"   kurva patah di K=4 -> siku terdeteksi K={siku}")
assert siku == 4, f"siku seharusnya 4, dapat {siku}"

# Siku yang sama harus ditemukan walau satuan biayanya diubah 1000 kali lipat.
siku_besar = elbow_cluster_count(K_RANGE, [c * 1000 for c in kurva_tajam])
assert siku_besar == siku, "siku berubah hanya karena satuan biaya diubah"
print("   satuan biaya dikali 1000 -> siku tetap K=4 (kedua sumbu dinormalkan)")

# Kurva lurus tidak punya siku: jarak ke garis harus nol di mana-mana.
lurus = [100.0 - 5 * i for i in range(len(K_RANGE))]
assert np.allclose(elbow_distances(K_RANGE, lurus), 0.0), "kurva lurus tidak boleh punya siku"
print("   kurva lurus -> jarak ke garis nol di seluruh titik")

# Ujung-ujung kurva selalu berjarak nol -- keduanya memang berada di garis itu.
jarak = elbow_distances(K_RANGE, kurva_tajam)
assert jarak[0] == 0 and jarak[-1] == 0, jarak
assert np.argmax(jarak) == K_RANGE.index(4)
print("   ujung kurva berjarak nol; puncaknya tepat di titik siku")

tabel = elbow_table(K_RANGE, kurva_tajam, cost_label="Cost")
assert list(tabel.columns) == ["K", "Cost", "Penurunan", "Jarak ke garis", "Titik siku"]
assert (tabel.loc[tabel["K"] == 4, "Titik siku"] == "<-- K dipilih").all()
assert (tabel["Titik siku"] != "").sum() == 1, "hanya satu baris boleh ditandai sebagai siku"
print("   tabel siku menandai tepat satu K")

print("\n== Gower Distance ==")
# Satu atribut numerik berentang 10 dan satu atribut kategorikal:
# jarak = (|0-10|/10 + 1) / 2 = 1,0 -- yaitu jarak maksimum.
num = np.array([[0.0], [10.0]])
kat = np.array([["a"], ["b"]])
G = gower_pairwise_distances(num, kat)
assert abs(G[0, 1] - 1.0) < 1e-12, G
print("   beda maksimum di kedua atribut -> jarak 1,0")

# Setengah jalan pada atribut numerik, kategori sama: (0,5 + 0) / 2 = 0,25.
num3 = np.array([[0.0], [5.0], [10.0]])
kat3 = np.array([["a"], ["a"], ["a"]])
G3 = gower_pairwise_distances(num3, kat3)
assert abs(G3[0, 1] - 0.25) < 1e-12, G3
print("   setengah rentang numerik, kategori sama -> 0,25")

# Sifat wajib sebuah matriks jarak.
rng = np.random.default_rng(3)
num_acak = rng.normal(size=(40, 3))
kat_acak = rng.choice(list("abcd"), size=(40, 2))
GA = gower_pairwise_distances(num_acak, kat_acak)
assert np.allclose(np.diag(GA), 0.0), "jarak ke diri sendiri harus 0"
assert np.allclose(GA, GA.T), "matriks jarak harus simetris"
assert GA.min() >= 0.0 and GA.max() <= 1.0, (GA.min(), GA.max())
print("   diagonal nol, simetris, dan selalu berada di rentang 0..1")

# Penskalaan tidak boleh mengubah apa pun: tiap suku sudah dibagi rentangnya.
GB = gower_pairwise_distances(num_acak * 137.0 + 9.0, kat_acak)
assert np.allclose(GA, GB), "Gower berubah oleh penskalaan -- pembagian rentang tidak jalan"
print("   kolom numerik dikali 137 dan digeser -> matriks tidak berubah")

# Atribut numerik yang konstan tidak boleh membuat pembagian nol.
G_konstan = gower_pairwise_distances(np.ones((5, 2)), np.array([["a"]] * 5))
assert np.isfinite(G_konstan).all() and np.allclose(G_konstan, 0.0)
print("   atribut konstan -> tidak ada pembagian nol")

print("\n== Silhouette di atas matriks Gower ==")
# Dua kelompok yang terpisah jelas pada numerik MAUPUN kategorikal.
num_pisah = np.vstack([rng.normal(0, 0.2, size=(60, 2)), rng.normal(10, 0.2, size=(60, 2))])
kat_pisah = np.array([["p", "q"]] * 60 + [["r", "s"]] * 60)
label_benar = np.array([0] * 60 + [1] * 60)
sil_bagus = gower_silhouette(num_pisah, kat_pisah, label_benar)
# Label yang diacak: klaster yang sama sekali tidak menggambarkan datanya.
label_acak = rng.permutation(label_benar)
sil_acak = gower_silhouette(num_pisah, kat_pisah, label_acak)
print(f"   label benar : {sil_bagus:.4f}")
print(f"   label acak  : {sil_acak:.4f}")
assert sil_bagus > 0.7, f"kelompok terpisah jelas seharusnya tinggi, dapat {sil_bagus}"
assert sil_acak < 0.1, f"label acak seharusnya mendekati nol, dapat {sil_acak}"
assert gower_silhouette(num_pisah, kat_pisah, np.zeros(120, dtype=int)) is None, \
    "satu klaster tunggal tidak punya Silhouette dan harus mengembalikan None"

print("\n== Calinski-Harabasz ==")
ch_bagus = safe_calinski_harabasz(num_pisah, label_benar)
ch_acak = safe_calinski_harabasz(num_pisah, label_acak)
print(f"   label benar : {ch_bagus:,.2f}")
print(f"   label acak  : {ch_acak:,.2f}")
assert ch_bagus > ch_acak * 100, "CH harus jauh lebih besar pada pemisahan yang benar"
assert safe_calinski_harabasz(num_pisah, np.zeros(120, dtype=int)) is None

print("\n== MAP: Average Precision ==")
# Susunan sempurna: seluruh item relevan berada di puncak.
assert average_precision_at_k([True, True, False, False], 4) == 1.0
print("   item relevan semua di puncak -> AP 1,0")

# rel = [1,0,1,0,0] dengan R=2: AP = (1/1 + 2/3) / 2 = 0,8333...
ap = average_precision_at_k([True, False, True, False, False], 5)
assert abs(ap - (1.0 + 2 / 3) / 2) < 1e-12, ap
print(f"   [1,0,1,0,0] -> AP {ap:.4f} (dihitung tangan: (1/1 + 2/3)/2)")

# Peringkat yang lebih baik harus bernilai lebih besar.
lebih_baik = average_precision_at_k([True, True, False, False, False], 5)
lebih_buruk = average_precision_at_k([False, False, False, True, True], 5)
assert lebih_baik > lebih_buruk, (lebih_baik, lebih_buruk)
print(f"   relevan di atas ({lebih_baik:.4f}) > relevan di bawah ({lebih_buruk:.4f})")

# Tidak ada item relevan sama sekali -> 0, bukan galat pembagian nol.
assert average_precision_at_k([False] * 5, 5) == 0.0

print("\n== NDCG ==")
assert ndcg_at_k([True, True, False, False], 4) == 1.0
print("   susunan sempurna -> NDCG 1,0")

# DCG dihitung tangan: 1/log2(2) + 1/log2(4) = 1 + 0,5 = 1,5
dcg = dcg_at_k([True, False, True, False, False], 5)
assert abs(dcg - 1.5) < 1e-12, dcg
# IDCG = 1/log2(2) + 1/log2(3) = 1 + 0,6309
ndcg = ndcg_at_k([True, False, True, False, False], 5)
assert abs(ndcg - 1.5 / (1 + 1 / np.log2(3))) < 1e-12, ndcg
print(f"   [1,0,1,0,0] -> DCG {dcg:.4f}, NDCG {ndcg:.4f} (cocok dengan hitungan tangan)")

for urutan in ([True] * 3 + [False] * 7, [False] * 7 + [True] * 3, [True, False] * 5):
    nilai = ndcg_at_k(urutan, 10)
    assert 0.0 <= nilai <= 1.0, (urutan, nilai)
print("   NDCG selalu berada di rentang 0..1")

print("\n== Rata-rata lintas kueri dan pembanding acak ==")
kueri = {
    "bagus": np.array([True, True, True, False, False, False, False, False]),
    "sedang": np.array([True, False, True, False, True, False, False, False]),
    "buruk": np.array([False, False, False, False, False, True, True, True]),
}
laporan = ranking_report(kueri, (3, 5))
assert list(laporan["Kueri"]) == ["bagus", "sedang", "buruk"]
assert set(laporan.columns) == {"Kueri", "Item relevan", "AP@3", "NDCG@3", "AP@5", "NDCG@5"}
assert (laporan["Item relevan"] == 3).all()
assert laporan.loc[0, "AP@5"] > laporan.loc[1, "AP@5"] > laporan.loc[2, "AP@5"]
print(laporan.to_string(index=False))

map5 = mean_average_precision(kueri.values(), 5)
ndcg5 = mean_ndcg(kueri.values(), 5)
assert abs(map5 - laporan["AP@5"].mean()) < 1e-4
assert abs(ndcg5 - laporan["NDCG@5"].mean()) < 1e-4
print(f"   MAP@5 {map5:.4f} = rata-rata kolom AP@5; NDCG@5 {ndcg5:.4f} = rata-rata kolom NDCG@5")

acak = random_baseline(kueri, (3, 5), runs=100, random_state=1)
assert list(acak["K"]) == [3, 5]
assert (acak["MAP acak"] > 0).all() and (acak["MAP acak"] < 1).all()
# Pembanding acak dipakai untuk menunjukkan sumbangan TF-IDF, jadi ia wajib
# berada di bawah peringkat yang benar-benar diurutkan.
assert acak.loc[acak["K"] == 5, "MAP acak"].iloc[0] < laporan.loc[0, "AP@5"]
print(acak.to_string(index=False))

# Diulang dengan seed yang sama harus memberi angka yang sama persis.
assert acak.equals(random_baseline(kueri, (3, 5), runs=100, random_state=1)), \
    "pembanding acak tidak reproducible"
print("   pembanding acak reproducible pada seed yang sama")

print("\nSEMUA ASSERT METRIK EVALUASI LOLOS")
