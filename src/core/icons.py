"""Ikon SVG inline untuk kartu dashboard.

SENGAJA SVG, bukan emoji. Emoji dirender pakai font sistem, jadi tinggi dan
lebarnya berbeda di Windows/macOS/Linux -- efeknya baris aktivitas jadi tidak
rata dan ikon di kartu langkah bergeser sendiri tergantung mesin yang membuka.
SVG ukurannya pasti, dan karena `stroke="currentColor"` warnanya otomatis ikut
warna teks elemen induk, sehingga satu ikon bisa dipakai untuk state normal,
terkunci (abu-abu), maupun selesai (hijau) tanpa perlu file terpisah.

Gaya gambarnya mengikuti ikon garis (outline, stroke-width seragam) supaya
konsisten dengan rancangan dashboard.
"""

from __future__ import annotations


# viewBox semua ikon 24x24 supaya `size` bisa diatur bebas tanpa mengubah path.
ICON_PATHS: dict[str, str] = {
    "calculator": (
        '<rect x="4" y="2" width="16" height="20" rx="2"/>'
        '<path d="M8 6h8"/>'
        '<path d="M8 10h.01"/><path d="M12 10h.01"/><path d="M16 10h.01"/>'
        '<path d="M8 14h.01"/><path d="M12 14h.01"/>'
        '<path d="M8 18h.01"/><path d="M12 18h.01"/>'
        '<path d="M16 14v4"/>'
    ),
    "utensils": (
        '<path d="m16 2-2.3 2.3a3 3 0 0 0 0 4.2l1.8 1.8a3 3 0 0 0 4.2 0L22 8"/>'
        '<path d="M15 15 3.3 3.3a4.2 4.2 0 0 0 0 6l7.3 7.3c.7.7 2 .7 2.8 0L15 15Zm0 0 7 7"/>'
        '<path d="m2.1 21.8 6.4-6.3"/>'
        '<path d="m19 5-7 7"/>'
    ),
    "dumbbell": (
        '<path d="m6.5 6.5 11 11"/>'
        '<path d="m21 21-1-1"/>'
        '<path d="m3 3 1 1"/>'
        '<path d="m18 22 4-4"/>'
        '<path d="m2 6 4-4"/>'
        '<path d="m3 10 7-7"/>'
        '<path d="m14 21 7-7"/>'
    ),
    "check": (
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="m9 12 2 2 4-4"/>'
    ),
    "lock": (
        '<rect x="3" y="11" width="18" height="11" rx="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    "history": (
        '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>'
        '<path d="M3 3v5h5"/>'
        '<path d="M12 7v5l4 2"/>'
    ),
    "hourglass": (
        '<path d="M5 22h14"/><path d="M5 2h14"/>'
        '<path d="M17 22v-4.2a2 2 0 0 0-.6-1.4L12 12l-4.4 4.4a2 2 0 0 0-.6 1.4V22"/>'
        '<path d="M7 2v4.2a2 2 0 0 0 .6 1.4L12 12l4.4-4.4a2 2 0 0 0 .6-1.4V2"/>'
    ),
    "lightbulb": (
        '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/>'
        '<path d="M9 18h6"/><path d="M10 22h4"/>'
    ),
    "party": (
        '<path d="M5.8 11.3 2 22l10.7-3.8"/>'
        '<path d="M4 3h.01"/><path d="M22 8h.01"/><path d="M15 2h.01"/><path d="M22 20h.01"/>'
        '<path d="m22 2-2.2.8a2.9 2.9 0 0 0-2 3.1c.1.9-.6 1.6-1.4 1.6h-.4c-.9 0-1.6.6-1.8 1.4L14 11"/>'
        '<path d="M11 13c1.9 1.9 2.8 4.2 2 5-.8.8-3.1-.1-5-2-1.9-1.9-2.8-4.2-2-5 .8-.8 3.1.1 5 2Z"/>'
    ),
    "flame": (
        '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.4-.5-2-1-3-1-2.1-.2-4 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.2.4-2.3 1-3a2.5 2.5 0 0 0 2.5 2.5Z"/>'
    ),
    "sunrise": (
        '<path d="M12 2v8"/><path d="m4.9 10.9 1.4 1.4"/><path d="M2 18h2"/>'
        '<path d="M20 18h2"/><path d="m17.7 12.3 1.4-1.4"/>'
        '<path d="M8 6l4-4 4 4"/>'
        '<path d="M16 18a4 4 0 0 0-8 0"/>'
        '<path d="M3 22h18"/>'
    ),
    "target": (
        '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>'
    ),
    "trending-down": (
        '<path d="M16 17h6v-6"/><path d="m22 17-8.5-8.5-5 5L2 7"/>'
    ),
    "trending-up": (
        '<path d="M16 7h6v6"/><path d="m22 7-8.5 8.5-5-5L2 17"/>'
    ),
    "minus": (
        '<path d="M5 12h14"/>'
    ),
}


def icon(name: str, *, size: int = 20, stroke_width: float = 1.8, css_class: str = "") -> str:
    """HTML satu ikon SVG. Balikan string kosong kalau namanya tidak dikenal
    supaya salah ketik nama ikon tidak sampai menjatuhkan render halaman."""
    paths = ICON_PATHS.get(name)
    if not paths:
        return ""

    classes = " ".join(part for part in ("nf-icon", css_class) if part)
    return (
        f'<svg class="{classes}" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="{stroke_width}" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" '
        f'focusable="false">{paths}</svg>'
    )
