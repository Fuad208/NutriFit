"""Utilitas pengiriman email (verifikasi akun & lupa password) via SMTP.

Kredensial SMTP dibaca dari .env / environment variable, lewat helper
`getenv()` yang sudah ada di src.database (konsisten dengan cara modul lain
baca konfigurasi). Tidak ada kredensial yang di-hardcode di sini.

Variabel .env yang dibutuhkan:
    SMTP_HOST       contoh: smtp.gmail.com
    SMTP_PORT       contoh: 587
    SMTP_USER       alamat pengirim, contoh: nutrifit.noreply@gmail.com
    SMTP_PASSWORD   App Password Gmail (BUKAN password akun biasa)
    SMTP_FROM       (opsional) nama+email pengirim yang tampil di inbox penerima
    APP_BASE_URL    contoh: http://localhost:8501  (dipakai untuk membangun link verifikasi/reset)
"""
from __future__ import annotations

from email.mime.text import MIMEText
import smtplib

from .database import getenv


class EmailNotConfiguredError(RuntimeError):
    """SMTP belum dikonfigurasi di .env."""


def smtp_configured() -> bool:
    """True bila host, user, dan password SMTP sudah terisi di .env."""
    return bool(getenv("SMTP_HOST") and getenv("SMTP_USER") and getenv("SMTP_PASSWORD"))


def app_base_url() -> str:
    """URL dasar aplikasi pengguna untuk menyusun link verifikasi/reset, tanpa slash di akhir."""
    return (getenv("APP_BASE_URL", "http://localhost:8501") or "http://localhost:8501").rstrip("/")


def send_email(to_email: str, subject: str, body: str) -> None:
    """Kirim email teks polos. Raise EmailNotConfiguredError kalau SMTP belum diisi di .env,
    supaya pemanggil bisa tampilkan pesan yang jelas alih-alih traceback mentah."""
    if not smtp_configured():
        raise EmailNotConfiguredError(
            "SMTP belum dikonfigurasi. Isi SMTP_HOST, SMTP_USER, SMTP_PASSWORD di file .env."
        )

    host = getenv("SMTP_HOST")
    port = int(getenv("SMTP_PORT", "587") or "587")
    user = getenv("SMTP_USER")
    password = getenv("SMTP_PASSWORD")
    sender = getenv("SMTP_FROM", user) or user

    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to_email

    with smtplib.SMTP(host, port, timeout=15) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(sender, [to_email], message.as_string())


def send_verification_email(to_email: str, name: str, token: str) -> None:
    """Kirim email berisi link verifikasi akun yang berlaku 24 jam."""
    link = f"{app_base_url()}/?verify={token}"
    body = (
        f"Halo {name},\n\n"
        "Terima kasih sudah mendaftar di NutriFit. Klik link berikut untuk memverifikasi "
        "alamat email Anda (berlaku 24 jam):\n\n"
        f"{link}\n\n"
        "Kalau Anda tidak merasa mendaftar di NutriFit, abaikan saja email ini.\n\n"
        "-- NutriFit"
    )
    send_email(to_email, "Verifikasi email NutriFit Anda", body)


def send_password_reset_email(to_email: str, name: str, token: str, base_url: str | None = None) -> None:
    """Kirim email berisi link reset password yang berlaku 1 jam."""
    link = f"{(base_url or app_base_url()).rstrip('/')}/?reset={token}"
    body = (
        f"Halo {name},\n\n"
        "Kami menerima permintaan reset password untuk akun NutriFit Anda. Klik link "
        f"berikut untuk membuat password baru (berlaku 1 jam):\n\n"
        f"{link}\n\n"
        "Kalau Anda tidak meminta reset password, abaikan saja email ini -- password Anda tidak akan berubah.\n\n"
        "-- NutriFit"
    )
    send_email(to_email, "Reset password NutriFit Anda", body)
