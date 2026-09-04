"""Printer capability profiles. XP-T80A is the reference 80mm ESC/POS profile."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class PrinterProfile:
    key: str
    label: str
    paper_mm: int = 80
    printable_mm: int = 72
    dpi: int = 203
    chars_normal: int = 48
    chars_font_b: int = 64
    encoding: str = 'cp437'
    cut_mode: str = 'partial'  # partial | full | none | partial_feed
    supports_qr: bool = True
    supports_barcode: bool = True
    supports_raster_logo: bool = True
    drawer_pin_default: int = 0
    feed_before_cut: int = 3
    notes: str = ''


XP_T80A = PrinterProfile(
    key='xp_t80a',
    label='Xprinter XP-T80A (80mm)',
    paper_mm=80,
    printable_mm=72,
    dpi=203,
    chars_normal=48,
    encoding='cp437',
    cut_mode='partial',
    supports_qr=True,
    supports_barcode=True,
    supports_raster_logo=True,
    drawer_pin_default=0,
    feed_before_cut=3,
    notes='Reference hardware for MBT POS Phase 1 ESC/POS engine.',
)

GENERIC_80MM = PrinterProfile(
    key='generic_80mm',
    label='Generic ESC/POS 80mm',
    paper_mm=80,
    printable_mm=72,
    dpi=203,
    chars_normal=48,
    encoding='cp437',
    cut_mode='partial',
    supports_qr=True,
    supports_barcode=True,
    supports_raster_logo=True,
)

PROFILES: Dict[str, PrinterProfile] = {
    XP_T80A.key: XP_T80A,
    GENERIC_80MM.key: GENERIC_80MM,
}


def get_profile(key: str | None = None) -> PrinterProfile:
    if not key:
        return XP_T80A
    return PROFILES.get(str(key).strip().lower(), XP_T80A)
