"""Decide what a second till launch should do. Tests pass the window lookup in."""
from __future__ import annotations


def resolve_second_launch(already_running: bool, find_window, foreground) -> str:
    """Return start, raised, or quiet. A missing window stays quiet."""
    if not already_running:
        return 'start'
    hwnd = find_window()
    if not hwnd:
        return 'quiet'
    foreground(hwnd)
    return 'raised'
