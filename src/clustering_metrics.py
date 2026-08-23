"""Metrik penilaian mutu klaster: Hopkins, jarak Gower, dan Rasio Hamming.

Dipakai notebook pengujian dan panel admin, BUKAN oleh aplikasi saat melayani
pengguna. Statistik Hopkins menguji apakah data layak diklasterkan sebelum
algoritma dijalankan; Rasio Hamming menilai pemisahan klaster kategorikal.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


DEFAULT_SAMPLE_RATIO = 0.10
DEFAULT_RUNS = 50


# --------------------------------------------------------------------------- #
# Jarak per tipe data
# --------------------------------------------------------------------------- #
def hamming_distance_matrix(values: np.ndarray) -> np.ndarray:
    """Matching dissimilarity: berapa atribut yang BERBEDA antar dua baris.

    Inilah jarak yang benar untuk data kategorikal -- tidak ada arti "selisih"
    antara 'Barbell' dan 'Dumbbell', yang ada hanya sama atau tidak sama.
    """
    return (values[:, None, :] != values[None, :, :]).sum(axis=2).astype(float)


def mixed_distance_matrix(numeric: np.ndarray, categorical: np.ndarray, gamma: float = 1.0) -> np.ndarray:
    """Jarak campuran K-Prototypes: kuadrat Euclid + gamma x ketidakcocokan.

    gamma=1.0 menyamai `kprototypes_distances` di src/recommender.py, sehingga
    angka yang dilaporkan notebook berasal dari definisi jarak yang sama persis
    dengan yang membentuk klaster di aplikasi.
    """
    numeric_part = ((numeric[:, None, :] - numeric[None, :, :]) ** 2).sum(axis=2)
    categorical_part = (categorical[:, None, :] != categorical[None, :, :]).sum(axis=2)
    return numeric_part + gamma * categorical_part


# --------------------------------------------------------------------------- #
# Hopkins Statistic
# --------------------------------------------------------------------------- #
def _nearest_distance(point_rows, reference_rows, metric) -> np.ndarray:
    """Jarak ke tetangga terdekat bagi tiap baris titik terhadap kumpulan referensi."""
    distances = metric(point_rows, reference_rows)
    return distances.min(axis=1)


def hopkins_numeric(data: np.ndarray, *, sample_ratio: float = DEFAULT_SAMPLE_RATIO,
                    random_state: int = 42) -> float:
    """Hopkins Statistic untuk data numerik.

    Mendekati 1  -> data sangat berkelompok, layak diklasterkan.
    Sekitar 0,5  -> sebaran data tidak berbeda dari acak seragam; klaster apa pun
                    yang ditemukan tidak lebih bermakna daripada memotong awan
                    titik secara sembarang.
    Mendekati 0  -> data tersebar sangat merata (menjauhi satu sama lain).
    """
    rng = np.random.default_rng(random_state)
    n, dim = data.shape
    m = max(5, int(sample_ratio * n))
    m = min(m, n - 1)

    # w: jarak titik ASLI ke tetangga terdekatnya (selain dirinya sendiri).
    sample_index = rng.choice(n, size=m, replace=False)
    real = data[sample_index]
    to_real = ((real[:, None, :] - data[None, :, :]) ** 2).sum(axis=2) ** 0.5
    to_real[np.arange(m), sample_index] = np.inf          # buang jarak ke diri sendiri
    w = to_real.min(axis=1)

    # u: jarak titik BUATAN (acak seragam di rentang data) ke titik asli terdekat.
    low, high = data.min(axis=0), data.max(axis=0)
    synthetic = rng.uniform(low, high, size=(m, dim))
    u = (((synthetic[:, None, :] - data[None, :, :]) ** 2).sum(axis=2) ** 0.5).min(axis=1)

    total = u.sum() + w.sum()
    return float(u.sum() / total) if total > 0 else 0.5


def hopkins_categorical(values: np.ndarray, *, sample_ratio: float = DEFAULT_SAMPLE_RATIO,
                        random_state: int = 42) -> float:
    """Hopkins untuk data kategorikal, memakai matching dissimilarity.

    Titik buatan dibentuk dengan mengambil tiap atribut secara acak seragam dari
    kategori yang MEMANG ADA pada atribut itu -- bukan dari ruang yang mustahil,
    supaya pembandingnya adil.
    """
    rng = np.random.default_rng(random_state)
    n, dim = values.shape
    m = max(5, int(sample_ratio * n))
    m = min(m, n - 1)

    sample_index = rng.choice(n, size=m, replace=False)
    real = values[sample_index]
    to_real = (real[:, None, :] != values[None, :, :]).sum(axis=2).astype(float)
    to_real[np.arange(m), sample_index] = np.inf
    w = to_real.min(axis=1)

    kategori = [np.unique(values[:, j]) for j in range(dim)]
    synthetic = np.column_stack([rng.choice(kategori[j], size=m) for j in range(dim)])
    u = (synthetic[:, None, :] != values[None, :, :]).sum(axis=2).astype(float).min(axis=1)

    total = u.sum() + w.sum()
    return float(u.sum() / total) if total > 0 else 0.5


def hopkins_mixed(numeric: np.ndarray, categorical: np.ndarray, *, gamma: float = 1.0,
                  sample_ratio: float = DEFAULT_SAMPLE_RATIO, random_state: int = 42) -> float:
    """Hopkins untuk data campuran, memakai jarak yang sama dengan K-Prototypes."""
    rng = np.random.default_rng(random_state)
    n, dim_num = numeric.shape
    dim_cat = categorical.shape[1]
    m = max(5, int(sample_ratio * n))
    m = min(m, n - 1)

    def jarak(a_num, a_cat, b_num, b_cat):
        """Jarak campuran antara dua kumpulan baris: kuadrat Euclid + gamma x ketidakcocokan kategori."""
        numerik = ((a_num[:, None, :] - b_num[None, :, :]) ** 2).sum(axis=2)
        kategorikal = (a_cat[:, None, :] != b_cat[None, :, :]).sum(axis=2)
        return numerik + gamma * kategorikal

    sample_index = rng.choice(n, size=m, replace=False)
    to_real = jarak(numeric[sample_index], categorical[sample_index], numeric, categorical)
    to_real[np.arange(m), sample_index] = np.inf
    w = to_real.min(axis=1)

    low, high = numeric.min(axis=0), numeric.max(axis=0)
    synth_num = rng.uniform(low, high, size=(m, dim_num))
    kategori = [np.unique(categorical[:, j]) for j in range(dim_cat)]
    synth_cat = np.column_stack([rng.choice(kategori[j], size=m) for j in range(dim_cat)])
    u = jarak(synth_num, synth_cat, numeric, categorical).min(axis=1)

    total = u.sum() + w.sum()
    return float(u.sum() / total) if total > 0 else 0.5


def hamming_separation(values: np.ndarray, labels: np.ndarray) -> dict:
    """Rata-rata jarak Hamming di dalam klaster dan antar klaster, beserta rasionya.

    Makin kecil rasionya makin terpisah klasternya.
    """
    distances = hamming_distance_matrix(values)
    same_cluster = labels[:, None] == labels[None, :]
    off_diagonal = ~np.eye(len(values), dtype=bool)

    within_mask = same_cluster & off_diagonal
    between_mask = (~same_cluster) & off_diagonal
    within = float(distances[within_mask].mean()) if within_mask.any() else 0.0
    between = float(distances[between_mask].mean()) if between_mask.any() else 0.0

    return {
        "within_cluster": within,
        "between_cluster": between,
        "ratio": float(within / between) if between else 0.0,
        "attributes": int(values.shape[1]),
    }


def interpret_hamming_ratio(ratio: float) -> str:
    """Terjemahkan rasio Hamming jadi kalimat penilaian mutu pemisahan klaster."""
    if ratio <= 0.35:
        return "Pemisahan sangat baik (anggota sekelompok jauh lebih mirip)"
    if ratio <= 0.60:
        return "Pemisahan baik"
    if ratio <= 0.85:
        return "Pemisahan lemah"
    return "Hampir tidak memisahkan apa pun"


def interpret_hopkins(value: float) -> str:
    """Terjemahkan nilai Hopkins jadi kalimat penilaian kelayakan data untuk diklasterkan."""
    if value >= 0.75:
        return "Sangat layak diklasterkan (struktur kelompok kuat)"
    if value >= 0.60:
        return "Layak diklasterkan (ada kecenderungan mengelompok)"
    if value > 0.45:
        return "Cenderung acak -- klaster kurang bermakna"
    return "Tersebar terlalu merata (anti-kelompok)"


# --------------------------------------------------------------------------- #
# Stabilitas antar-eksekusi
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StabilityResult:
    """Ringkasan satu metrik pada banyak eksekusi berbeda."""

    metric: str
    runs: int
    values: np.ndarray

    @property
    def mean(self) -> float:
        """Rata-rata nilai metrik dari seluruh eksekusi."""
        return float(np.mean(self.values))

    @property
    def variance(self) -> float:
        """Varians sampel nilai metrik antar-eksekusi."""
        return float(np.var(self.values, ddof=1)) if len(self.values) > 1 else 0.0

    @property
    def std(self) -> float:
        """Simpangan baku sampel nilai metrik antar-eksekusi."""
        return float(np.std(self.values, ddof=1)) if len(self.values) > 1 else 0.0

    @property
    def spread(self) -> tuple[float, float]:
        """Pasangan nilai terendah dan tertinggi dari seluruh eksekusi."""
        return float(np.min(self.values)), float(np.max(self.values))

    @property
    def coefficient_of_variation(self) -> float:
        """Simpangan baku relatif terhadap rata-rata; membuat metrik berskala
        beda (Silhouette 0-1 vs Cost ratusan) bisa dibandingkan langsung."""
        return float(self.std / self.mean) if self.mean else 0.0

    @property
    def is_stable(self) -> bool:
        """True bila variasi antar-eksekusi di bawah 1 persen, yaitu hasilnya bisa dianggap konsisten."""
        # Di bawah 1% variasi relatif, perbedaan antar-eksekusi tidak akan
        # mengubah satu pun angka yang dilaporkan pada dua desimal.
        return self.coefficient_of_variation < 0.01

    def summary(self) -> dict:
        """Ringkas seluruh angka kestabilan jadi satu baris tabel siap ditampilkan."""
        low, high = self.spread
        return {
            "Metrik": self.metric,
            "Eksekusi": self.runs,
            "Rata-rata": round(self.mean, 4),
            "Varians": round(self.variance, 6),
            "Simpangan baku": round(self.std, 6),
            "Minimum": round(low, 4),
            "Maksimum": round(high, 4),
            "Koef. variasi": f"{self.coefficient_of_variation:.4%}",
            "Kesimpulan": "Konsisten" if self.is_stable else "Berubah antar-eksekusi",
        }


def stability_over_runs(run_once, *, runs: int = DEFAULT_RUNS, metric: str = "") -> StabilityResult:
    """Jalankan `run_once(seed)` sebanyak `runs` kali dan rangkum sebarannya.

    `run_once` menerima satu bilangan seed dan mengembalikan satu nilai metrik.
    Seed-nya 0..runs-1 supaya hasilnya sendiri bisa direproduksi.
    """
    values = np.array([float(run_once(seed)) for seed in range(runs)])
    return StabilityResult(metric=metric, runs=runs, values=values)


def stability_table(results: list[StabilityResult]) -> pd.DataFrame:
    """Susun beberapa StabilityResult jadi satu DataFrame perbandingan."""
    return pd.DataFrame([r.summary() for r in results])
