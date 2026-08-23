"""Isolasi pengujian di tingkat schema Postgres.

`pakai_schema_uji()` mengisi env POSTGRES_SCHEMA dengan schema sekali-pakai,
membuangnya lebih dulu supaya mulai dari nol, lalu membuangnya lagi lewat atexit.
Lihat docs/catatan-desain.md bagian 19.
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
    """Jalankan satu perintah DDL lewat koneksi biasa.

    Dibungkus `ulangi_bila_koneksi_putus` dengan alasan yang sama seperti di
    aplikasi: pooler Supabase sesekali memutus koneksi tanpa pemberitahuan, dan
    kalau itu kebetulan mengenai DROP SCHEMA di akhir pengujian, schema ujinya
    tertinggal dan mengacaukan eksekusi berikutnya. Perintah yang dipakai di
    sini seluruhnya memakai IF EXISTS, jadi aman diulang.
    """
    from src.database import SQLStore, ulangi_bila_koneksi_putus

    @ulangi_bila_koneksi_putus
    def _jalankan() -> None:
        store = SQLStore()
        # DROP/CREATE SCHEMA tidak bergantung pada search_path, jadi tetap aman
        # dijalankan lewat koneksi yang search_path-nya menunjuk schema yang
        # kebetulan belum ada.
        with store.connection() as koneksi:
            with koneksi.cursor() as kursor:
                kursor.execute(perintah)

    _jalankan()


    # Koneksi yang ditinggalkan menggantung di tengah transaksi menahan kunci pada
    # schema uji, sehingga DROP SCHEMA pada eksekusi berikutnya bisa menggantung.
    # Timeout di bawah membuat koneksi seperti itu dilepas sendiri.
IDLE_TX_TIMEOUT_MS = "30000"
LOCK_TIMEOUT_MS = "15000"


def _pemegang_kunci(schema: str) -> str:
    """Ringkasan sesi lain yang sedang memegang kunci di schema uji, untuk pesan galat."""
    try:
        from src.database import SQLStore

        with SQLStore().connection() as koneksi:
            with koneksi.cursor() as kursor:
                kursor.execute(
                    """
                    SELECT pid, state, query
                      FROM pg_stat_activity
                     WHERE pid <> pg_backend_pid()
                       AND datname = current_database()
                       AND state LIKE 'idle in transaction%'
                    """
                )
                baris = kursor.fetchall()
    except Exception:                                    # diagnosis, bukan bagian uji
        return ""
    if not baris:
        return ""
    isi = "; ".join(f"pid {r['pid']} ({r['state']})" for r in baris)
    return (
        f"\n[isolasi] sesi menggantung yang mungkin memegang kunci {schema}: {isi}"
        f"\n[isolasi] periksa dulu query-nya, lalu: SELECT pg_terminate_backend(<pid>)"
    )


def pakai_schema_uji(nama: str) -> str:
    """Alihkan seluruh akses database ke schema uji yang kosong dan sekali pakai."""
    schema = f"uji_{nama}"
    os.environ["POSTGRES_SCHEMA"] = schema
    os.environ.setdefault("POSTGRES_IDLE_TX_TIMEOUT_MS", IDLE_TX_TIMEOUT_MS)
    os.environ.setdefault("POSTGRES_LOCK_TIMEOUT_MS", LOCK_TIMEOUT_MS)

    from src.database import reset_connection_cache

    try:
        _jalankan_ddl(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    except Exception as galat:
        raise RuntimeError(
            f"gagal membuang schema uji {schema}: {galat}{_pemegang_kunci(schema)}"
        ) from galat
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
