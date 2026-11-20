"""Shop categories exist only when this shop creates or uses them."""
from __future__ import annotations

import re
import sqlite3

# Names that older builds inserted into every new shop. They are not a catalog.
RETIRED_SEED_NAMES = frozenset({
    'general', 'grocery', 'pharmacy', 'electronics', 'clothing',
    'hardware', 'beverages', 'beauty',
})

_BAD_NAME = re.compile(r'[\x00-\x1f\\/]|\.\.')
MAX_NAME = 80
MAX_DESCRIPTION = 240


def normalize_category_name(value) -> str:
    """Trim ends and collapse inner whitespace. Case is preserved for display."""
    return ' '.join(str(value or '').replace('\u00a0', ' ').split())


def category_name_error(name: str) -> str:
    if not name:
        return 'Enter a category name.'
    if len(name) > MAX_NAME:
        return f'Category names can be at most {MAX_NAME} characters.'
    if _BAD_NAME.search(name):
        return 'That category name is not allowed.'
    return ''


def category_key(name: str) -> str:
    return normalize_category_name(name).casefold()


def _cell(row, name: str, index: int):
    if row is None:
        return None
    if isinstance(row, sqlite3.Row) or hasattr(row, 'keys'):
        return row[name]
    return row[index]


def find_category(conn, name: str):
    """Case- and space-insensitive match. Returns a row or None."""
    key = category_key(name)
    if not key:
        return None
    for row in conn.execute("SELECT * FROM categories").fetchall():
        if category_key(_cell(row, 'name', 1) or '') == key:
            return row
    return None


def product_counts(conn) -> dict:
    counts = {}
    try:
        rows = conn.execute("SELECT category FROM products").fetchall()
    except sqlite3.Error:
        return counts
    for row in rows:
        raw = _cell(row, 'category', 0)
        key = category_key(raw or '')
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def clear_products_in_category(conn, name: str) -> int:
    """Leave products in place and remove only the category label."""
    key = category_key(name)
    if not key:
        return 0
    changed = 0
    rows = conn.execute("SELECT id, category FROM products").fetchall()
    for row in rows:
        if category_key(_cell(row, 'category', 1) or '') != key:
            continue
        conn.execute("UPDATE products SET category='' WHERE id=?", (_cell(row, 'id', 0),))
        changed += 1
    return changed


def sync_shop_categories(conn) -> None:
    """Record categories this shop already uses. Never insert a built-in list.

    A previously auto-inserted default is removed only when no product uses it.
    """
    used = []
    seen = set()
    try:
        rows = conn.execute(
            "SELECT DISTINCT category FROM products "
            "WHERE category IS NOT NULL AND TRIM(category) != ''"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    for row in rows:
        name = normalize_category_name(_cell(row, 'category', 0) or '')
        if category_name_error(name):
            continue
        key = category_key(name)
        if key in seen:
            continue
        seen.add(key)
        used.append(name)
    try:
        from desktop.utils.category_suggest import suggest_visual_for_category_name
    except Exception:
        suggest_visual_for_category_name = None
    for name in used:
        if find_category(conn, name):
            continue
        vis = suggest_visual_for_category_name(name) if suggest_visual_for_category_name else {}
        try:
            conn.execute(
                "INSERT INTO categories "
                "(name, visual_type, icon_name, accent_color, is_active) "
                "VALUES (?,?,?,?,1)",
                (name, (vis or {}).get('visual_type') or 'icon',
                 (vis or {}).get('icon_name') or 'generic/general-product',
                 (vis or {}).get('accent_color') or '#3B82F6'),
            )
        except sqlite3.IntegrityError:
            pass
    # One startup cleanup of the old built-in list. A name the shop creates later,
    # even if it matches that old list, is kept.
    try:
        flag = conn.execute(
            "SELECT value FROM system_settings WHERE key='category_seed_cleaned'"
        ).fetchone()
    except sqlite3.Error:
        flag = ('1',)
    if not flag:
        try:
            existing = conn.execute("SELECT id, name FROM categories").fetchall()
        except sqlite3.Error:
            existing = []
        for row in existing:
            key = category_key(_cell(row, 'name', 1) or '')
            if key in RETIRED_SEED_NAMES and key not in seen:
                conn.execute("DELETE FROM categories WHERE id=?", (_cell(row, 'id', 0),))
        try:
            conn.execute(
                "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('category_seed_cleaned', '1')"
            )
        except sqlite3.Error:
            pass
