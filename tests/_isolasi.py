"""Isolasi penyimpanan untuk skrip pengujian.

Penyimpanan aplikasi cuma satu (Supabase), jadi skrip uji tidak punya penampung
sementara di luar database. Isolasinya dilakukan di tingkat SCHEMA Postgres:
tiap skrip memakai schema tersendiri yang dibuat dari nol di awal dan dibuang
lagi setelah selesai.

Yang membuat ini aman:

- `POSTGRES_SCHEMA` mengunci `search_path` koneksi ke schema uji saja, TANPA
  `public` di belakangnya -- jadi kalau ada tabel yang belum terbentuk, query-nya
  gagal terang-terangan alih-alih diam-diam membaca data asli.
- Tabelnya dibentuk oleh `ensure_schema()` yang sama dengan yang dipakai
  aplikasi, sehingga yang diuji benar-benar skema yang sesungguhnya.
- Schema dibuang di awal DAN lewat atexit di akhir, jadi eksekusi yang putus
  di tengah tidak meninggalkan sampah yang mengacaukan eksekusi berikutnya.

Dipanggil PALING ATAS di tiap skrip uji, sebelum apa pun dari `src` diimpor.
"""

from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _jalankan_ddl(perintah: str) -> None:
    """Jalankan satu perintah DDL lewat koneksi biasa."""
    from src.database import SQLStore

    store = SQLStore()
    # DROP/CREATE SCHEMA tidak bergantung pada search_path, jadi tetap aman
    # dijalankan lewat koneksi yang search_path-nya menunjuk schema yang
    # kebetulan belum ada.
    with store.connection() as koneksi:
        with koneksi.cursor() as kursor:
            kursor.execute(perintah)


def pakai_schema_uji(nama: str) -> str:
    """Alihkan seluruh akses database ke schema uji yang kosong dan sekali pakai."""
    schema = f"uji_{nama}"
    os.environ["POSTGRES_SCHEMA"] = schema

    from src.database import reset_connection_cache

    _jalankan_ddl(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    # Cache koneksi DAN penanda _SCHEMA_READY ikut dikosongkan, supaya
    # ensure_schema() benar-benar membangun ulang tabelnya setelah di-drop.
    reset_connection_cache()

    def _bersihkan() -> None:
        """Buang schema uji saat proses berakhir, termasuk bila pengujian gagal di tengah."""
        try:
            _jalankan_ddl(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            reset_connection_cache()
            print(f"[isolasi] schema {schema} dibuang")
        except Exception as galat:                      # jangan menutupi hasil uji
            print(f"[isolasi] gagal membuang schema {schema}: {galat}")

    atexit.register(_bersihkan)
    print(f"[isolasi] schema uji: {schema} (data asli di schema public tidak disentuh)")
    return schema
