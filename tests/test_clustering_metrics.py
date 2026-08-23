"""Uji metrik dan kestabilan klaster: Hopkins, Gower, Rasio Hamming, dan reproduksibilitas."""
import sys
from pathlib import Path

ROOT = Path(r"c:\Kuliah\Semester 8\Tugas Akhir\Coding\NutriFit")
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from src.clustering_metrics import (  # noqa: E402
    hamming_distance_matrix,
    hopkins_categorical,
    hopkins_mixed,
    hopkins_numeric,
    interpret_hopkins,
    mixed_distance_matrix,
    stability_over_runs,
)

rng = np.random.default_rng(7)

print("== Hopkins: data numerik ==")
# Tiga kelompok yang terpisah sangat jauh.
berkelompok = np.vstack([
    rng.normal(loc, 0.25, size=(120, 4))
    for loc in ([0, 0, 0, 0], [30, 30, 30, 30], [60, 0, 60, 0])
])
h_kelompok = hopkins_numeric(berkelompok, random_state=1)

# Sebaran acak seragam pada rentang yang sama.
acak = rng.uniform(0, 60, size=(360, 4))
h_acak = hopkins_numeric(acak, random_state=1)

# Kisi teratur: titik justru saling berjauhan secara merata.
sisi = np.linspace(0, 60, 8)
kisi = np.array([[a, b, c, d] for a in sisi for b in sisi[:3] for c in sisi[:3] for d in sisi[:2]])
h_kisi = hopkins_numeric(kisi, random_state=1)

print(f"   berkelompok jelas : {h_kelompok:.4f}   {interpret_hopkins(h_kelompok)}")
print(f"   acak seragam      : {h_acak:.4f}   {interpret_hopkins(h_acak)}")
print(f"   kisi teratur      : {h_kisi:.4f}   {interpret_hopkins(h_kisi)}")

assert h_kelompok > 0.75, f"data berkelompok seharusnya mendekati 1, dapat {h_kelompok}"
assert 0.40 < h_acak < 0.60, f"data acak seharusnya sekitar 0,5, dapat {h_acak}"
assert h_kisi < h_acak, "kisi teratur seharusnya lebih rendah daripada acak"
assert h_kelompok > h_acak > h_kisi, "urutan ketiganya terbalik"

print("\n== Hopkins: data kategorikal ==")
# Berkelompok: tiga pola atribut yang berulang.
pola = np.array([["a", "x", "1"], ["b", "y", "2"], ["c", "z", "3"]])
kat_kelompok = pola[rng.integers(0, 3, size=300)]
h_kat_kelompok = hopkins_categorical(kat_kelompok, random_state=1)

# Acak: tiap atribut diundi bebas.
kat_acak = np.column_stack([
    rng.choice(["a", "b", "c"], 300),
    rng.choice(["x", "y", "z"], 300),
    rng.choice(["1", "2", "3"], 300),
])
h_kat_acak = hopkins_categorical(kat_acak, random_state=1)
print(f"   pola berulang     : {h_kat_kelompok:.4f}")
print(f"   atribut acak      : {h_kat_acak:.4f}")
assert h_kat_kelompok > h_kat_acak, "pola berulang seharusnya lebih layak diklaster"

print("\n== Hopkins: data campuran ==")
num_kelompok = np.vstack([rng.normal(loc, 0.3, size=(150, 3)) for loc in ([0, 0, 0], [20, 20, 20])])
cat_kelompok = np.repeat(np.array([["p", "q"], ["r", "s"]]), 150, axis=0)
h_mix_kelompok = hopkins_mixed(num_kelompok, cat_kelompok, random_state=1)

num_acak = rng.uniform(0, 20, size=(300, 3))
cat_acak = np.column_stack([rng.choice(["p", "r"], 300), rng.choice(["q", "s"], 300)])
h_mix_acak = hopkins_mixed(num_acak, cat_acak, random_state=1)
print(f"   berkelompok       : {h_mix_kelompok:.4f}")
print(f"   acak              : {h_mix_acak:.4f}")
assert h_mix_kelompok > h_mix_acak

print("\n== Hopkins tidak boleh bergantung pada seed secara liar ==")
nilai = [hopkins_numeric(berkelompok, random_state=s) for s in range(10)]
print(f"   10 seed berbeda   : {min(nilai):.4f} - {max(nilai):.4f}")
assert max(nilai) - min(nilai) < 0.20, f"terlalu peka terhadap seed: {nilai}"
assert all(v > 0.70 for v in nilai)

print("\n== Matriks jarak ==")
nilai_kat = np.array([["a", "x"], ["a", "y"], ["b", "z"]])
H = hamming_distance_matrix(nilai_kat)
assert H.shape == (3, 3)
assert (np.diag(H) == 0).all(), "jarak ke diri sendiri harus 0"
assert H[0, 1] == 1 and H[0, 2] == 2, H          # beda 1 atribut, lalu 2 atribut
assert (H == H.T).all(), "matriks jarak harus simetris"
print("   Hamming: diagonal 0, simetris, hitungan ketidakcocokan benar")

num = np.array([[0.0, 0.0], [3.0, 4.0]])
kat = np.array([["a"], ["b"]])
M = mixed_distance_matrix(num, kat, gamma=1.0)
# kuadrat Euclid 3-4-5 = 25, ditambah 1 ketidakcocokan kategorikal
assert abs(M[0, 1] - 26.0) < 1e-9, M
print("   Campuran: kuadrat Euclid + gamma x ketidakcocokan = 25 + 1 = 26")

print("\n== Uji stabilitas ==")
tetap = stability_over_runs(lambda seed: 42.0, runs=20, metric="deterministik")
assert tetap.variance == 0.0 and tetap.is_stable
print(f"   nilai tetap  -> varians {tetap.variance}, {tetap.summary()['Kesimpulan']}")

berubah = stability_over_runs(
    lambda seed: 100.0 + np.random.default_rng(seed).normal(0, 15), runs=50, metric="berayun"
)
assert berubah.variance > 0 and not berubah.is_stable
print(f"   nilai berayun-> varians {berubah.variance:.2f}, {berubah.summary()['Kesimpulan']}")

halus = stability_over_runs(
    lambda seed: 100.0 + np.random.default_rng(seed).normal(0, 0.05), runs=50, metric="hampir tetap"
)
assert halus.is_stable, halus.summary()
print(f"   goyangan kecil-> koef. variasi {halus.coefficient_of_variation:.5%}, dinilai konsisten")

print("\nSEMUA ASSERT METRIK KLASTERISASI LOLOS")
