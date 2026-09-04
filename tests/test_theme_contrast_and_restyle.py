"""Theme regressions: no frozen palette colours, and readable body text.

Two failure modes this guards:

1.  A widget styled inline while dark mode was active keeps those hexes after a
    switch to light (dark navy text on a white card, measured as low as 1.8:1).
    `theme.install_style_capture` stores each inline stylesheet as a
    palette-token template so `restyle_themed_widgets` can replay it; this test
    fails if that chain stops working.
2.  A palette token pair drops below the WCAG minimum for the surface it is
    used on, in either mode.

Pure-logic tests: no QApplication, no display, no database.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from desktop.utils.theme import (  # noqa: E402
    C, DARK, LIGHT, ThemeManager, qss_alpha, render_style, tokenize_style)

HEX6 = re.compile(r'#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])')


def _lin(channel: float) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def blend(fg: str, bg: str, alpha: float) -> str:
    """Flatten a translucent fill onto an opaque surface."""
    f = fg.lstrip('#')
    b = bg.lstrip('#')
    out = []
    for i in (0, 2, 4):
        fv, bv = int(f[i:i + 2], 16), int(b[i:i + 2], 16)
        out.append(round(fv * alpha + bv * (1 - alpha)))
    return '#%02X%02X%02X' % tuple(out)


# (foreground token, background token, minimum ratio, why)
BODY_TEXT_PAIRS = [
    ('text', 'app', 4.5, 'page body text'),
    ('text', 'surface', 4.5, 'page body text'),
    ('text', 'card', 4.5, 'card body text'),
    ('text', 'card2', 4.5, 'nested card body text'),
    ('text', 'panel', 4.5, 'panel body text'),
    ('text', 'input', 4.5, 'typed input text'),
    ('text', 'hover', 4.5, 'hovered row text'),
    ('text', 'selected', 4.5, 'selected row text'),
    ('text2', 'app', 4.5, 'secondary text on page'),
    ('text2', 'surface', 4.5, 'secondary text'),
    ('text2', 'card', 4.5, 'form labels on cards'),
    ('text2', 'card2', 4.5, 'form labels on nested cards'),
    ('text2', 'panel', 4.5, 'form labels on panels'),
    ('muted', 'app', 4.5, 'captions on page'),
    ('muted', 'surface', 4.5, 'captions'),
    ('muted', 'card', 4.5, 'captions on cards'),
    ('muted', 'card2', 4.5, 'captions on nested cards'),
    ('muted', 'panel', 4.5, 'captions on panels'),
    ('muted', 'input', 4.5, 'input placeholders'),
    ('gold_fg', 'gold', 4.5, 'primary button label'),
    ('gold_fg', 'gold_lt', 4.5, 'primary button label (hover)'),
    ('gold_fg', 'gold_dk', 4.5, 'primary button label (pressed)'),
    ('on_danger', 'err', 4.5, 'danger button label'),
    ('on_danger', 'err_lt', 4.5, 'danger button label (hover)'),
    ('on_danger', 'err_dk', 4.5, 'danger button label (pressed)'),
    ('on_success', 'ok', 4.5, 'success button label'),
    ('on_success', 'ok_lt', 4.5, 'success button label (hover)'),
    ('on_success', 'ok_dk', 4.5, 'success button label (pressed)'),
    ('ok', 'surface', 4.5, 'success status text'),
    ('ok', 'card', 4.5, 'success status text on card'),
    ('warn', 'surface', 4.5, 'warning status text'),
    ('warn', 'card', 4.5, 'warning status text on card'),
    ('err', 'surface', 4.5, 'error status text'),
    ('err', 'card', 4.5, 'error status text on card'),
    ('info', 'surface', 4.5, 'info status text'),
    ('info', 'card', 4.5, 'info status text on card'),
    ('gold', 'surface', 4.5, 'accent text'),
    ('gold', 'card', 4.5, 'accent text on card'),
    ('gold', 'card2', 4.5, 'accent text on nested card'),
]

# Meaningful non-text boundaries only need 3:1.
BORDER_PAIRS = [
    ('border2', 'card', 3.0, 'control outline'),
    ('border2', 'card2', 3.0, 'control outline on nested card'),
    ('border2', 'input', 3.0, 'input outline'),
    ('border2', 'panel', 3.0, 'control outline on panel'),
    ('focus', 'card', 3.0, 'focus ring'),
    ('focus', 'input', 3.0, 'focus ring on inputs'),
]

# Disabled controls: the label must remain legible on the disabled fill.
DISABLED_PAIRS = [
    ('muted', 'panel', 4.5, 'disabled button label'),
    ('muted', 'input', 4.5, 'disabled input text'),
]

# Accent ink drawn on its own translucent tint (selected pills, cue strips).
TINTED_INK_PAIRS = [
    ('gold_ink', 'gold', 0.22, 'surface', 4.5, 'selected section pill'),
    ('gold_ink', 'gold', 0.22, 'card', 4.5, 'selected section pill on card'),
    ('gold_ink', 'gold', 0.12, 'surface', 4.5, 'accent tip / cue strip'),
]

# Badges use solid `*_dim` fills so their contrast never depends on the
# surface behind them. (ink token, fill token, minimum, why)
BADGE_PAIRS = [
    ('ok', 'ok_dim', 4.5, 'success badge'),
    ('warn', 'warn_dim', 4.5, 'warning badge'),
    ('err', 'err_dim', 4.5, 'danger badge'),
    ('info', 'info_dim', 4.5, 'info badge'),
    ('gold', 'gold_dim', 4.5, 'accent badge'),
    ('text2', 'panel', 4.5, 'neutral badge'),
]

PALETTES = (('dark', DARK), ('light', LIGHT))


class PaletteContrastTests(unittest.TestCase):
    """Body text >= 4.5:1 and meaningful borders >= 3:1 in both modes."""

    def test_palettes_expose_identical_tokens(self):
        self.assertEqual(set(DARK), set(LIGHT))

    def test_body_text_and_border_contrast(self):
        failures = []
        pairs = BODY_TEXT_PAIRS + BORDER_PAIRS + BADGE_PAIRS + DISABLED_PAIRS
        for mode, palette in PALETTES:
            for fg, bg, need, why in pairs:
                ratio = contrast(palette[fg], palette[bg])
                if ratio < need:
                    failures.append(
                        f'{mode}: {fg}({palette[fg]}) on {bg}({palette[bg]}) '
                        f'= {ratio:.2f}:1, need {need}:1 — {why}')
        self.assertEqual(failures, [], 'contrast regressions:\n' + '\n'.join(failures))

    def test_tinted_ink_contrast(self):
        """Accent/status ink on its own translucent tint stays readable."""
        failures = []
        for mode, palette in PALETTES:
            for ink, tint, alpha, base, need, why in TINTED_INK_PAIRS:
                bg = blend(palette[tint], palette[base], alpha)
                ratio = contrast(palette[ink], bg)
                if ratio < need:
                    failures.append(
                        f'{mode}: {ink}({palette[ink]}) on {int(alpha * 100)}% '
                        f'{tint} over {base} ({bg}) = {ratio:.2f}:1, '
                        f'need {need}:1 — {why}')
        self.assertEqual(failures, [], 'tinted contrast regressions:\n'
                         + '\n'.join(failures))

    def test_badge_fills_are_solid(self):
        """Badge backgrounds must not be translucent.

        A translucent fill inherits luminance from whatever card sits behind
        it, so the same badge measured differently on `card` and `card2`.
        """
        from desktop.utils.widgets import badge_qss
        for mode, is_light in (('dark', False), ('light', True)):
            ThemeManager.apply(is_light, force=True)
            for tone in ('ok', 'warn', 'err', 'info', 'gold', 'muted'):
                qss = badge_qss(tone)
                bg = re.search(r'background:([^;]+);', qss).group(1).strip()
                self.assertFalse(
                    bg.startswith('rgba'),
                    f'{mode}/{tone} badge fill is translucent: {bg}')


class StyleTemplateTests(unittest.TestCase):
    """A stylesheet built in one palette must re-render in the other."""

    def setUp(self):
        self._was_light = ThemeManager.is_light()

    def tearDown(self):
        ThemeManager.apply(self._was_light, force=True)

    def _roundtrip(self, sheet_for):
        """Build a sheet in one mode, replay it in the other, compare."""
        ThemeManager.apply(False, force=True)
        dark_sheet = sheet_for(C)
        template = tokenize_style(dark_sheet)
        self.assertIsNotNone(template, f'not tokenised: {dark_sheet}')

        ThemeManager.apply(True, force=True)
        rendered = render_style(template)
        expected = sheet_for(C)
        return rendered, expected

    def test_label_style_follows_theme(self):
        rendered, expected = self._roundtrip(
            lambda p: (f"color:{p['text2']}; font-size:13px; "
                       f"background:transparent; border:none;"))
        self.assertEqual(rendered, expected)

    def test_card_style_follows_theme(self):
        rendered, expected = self._roundtrip(
            lambda p: (f"QFrame {{ background:{p['card']}; "
                       f"border:1px solid {p['border']}; border-radius:12px; }}"
                       f"QLabel {{ color:{p['text']}; }}"))
        self.assertEqual(rendered, expected)

    def test_translucent_fill_follows_theme(self):
        rendered, expected = self._roundtrip(
            lambda p: (f"QLabel {{ background:{qss_alpha(p['ok'], 0.15)}; "
                       f"color:{p['ok']}; }}"))
        self.assertEqual(rendered, expected)

    def test_no_inactive_palette_hex_survives_render(self):
        """The rendered sheet must not contain any dark-only colour in light."""
        ThemeManager.apply(False, force=True)
        sheet = (f"QWidget {{ background:{C['card']}; color:{C['text2']}; "
                 f"border:1px solid {C['border']}; }}"
                 f"QLabel#cap {{ color:{C['muted']}; }}")
        template = tokenize_style(sheet)
        self.assertIsNotNone(template)

        ThemeManager.apply(True, force=True)
        rendered = render_style(template).lower()
        light_hexes = {v.lower() for v in LIGHT.values() if isinstance(v, str)}
        dark_only = {v.lower() for v in DARK.values()
                     if isinstance(v, str) and v.lower() not in light_hexes}
        leaked = sorted(set(HEX6.findall(rendered)) & dark_only)
        self.assertEqual(leaked, [], f'frozen dark colours left in {rendered}')

    def test_accent_ink_on_a_translucent_tint_is_tokenised(self):
        """Gold ink on a 12% gold tint must not stay literal.

        Ink on an *opaque* accent fill is deliberately left alone (guessing
        there flips button labels), but a tint is not a fill: the surface
        underneath still changes, and leaving the hex froze the settings
        scroll cue at bright dark-mode gold on a near-white strip (1.27:1).
        """
        ThemeManager.apply(False, force=True)
        sheet = (f"color:{C['gold']}; background:{qss_alpha(C['gold'], 0.12)}; "
                 f"border:1px solid {qss_alpha(C['gold'], 0.35)};")
        template = tokenize_style(sheet)
        self.assertIsNotNone(template)
        self.assertIn('@@gold_ink@@', template)

        ThemeManager.apply(True, force=True)
        rendered = render_style(template).lower()
        self.assertNotIn(DARK['gold'].lower(), rendered)
        self.assertIn(LIGHT['gold_ink'].lower(), rendered)

    def test_qss_alpha_is_read_as_translucent(self):
        """`qss_alpha` emits Qt's 0-255 alpha; 31 is not opaque."""
        from desktop.utils.theme import _background_token
        ThemeManager.apply(False, force=True)
        _, opaque = _background_token(f"background:{qss_alpha(C['gold'], 0.12)};")
        self.assertFalse(opaque)
        _, opaque = _background_token(f"background:{C['gold']};")
        self.assertTrue(opaque)

    def test_on_tone_ink_is_not_guessed_into_body_text(self):
        """Ink on a saturated fill must never be rewritten to `text`.

        Mapping the deep navy on a gold button to `text` would render white
        text on light-mode gold at 1.9:1.
        """
        ThemeManager.apply(False, force=True)
        sheet = (f"QPushButton {{ background:{C['gold']}; "
                 f"color:{C['gold_fg']}; }}")
        template = tokenize_style(sheet)
        self.assertIsNotNone(template)
        self.assertNotIn('@@text@@', template)

        ThemeManager.apply(True, force=True)
        rendered = render_style(template)
        self.assertIn(LIGHT['gold'], rendered)
        self.assertIn(LIGHT['gold_fg'], rendered)
        self.assertGreaterEqual(contrast(LIGHT['gold_fg'], LIGHT['gold']), 4.5)


class StyleCaptureInstallTests(unittest.TestCase):
    """The capture hook must be installed and idempotent."""

    def test_capture_is_installed_on_import(self):
        from PyQt5.QtWidgets import QWidget
        from desktop.utils.theme import install_style_capture
        self.assertTrue(hasattr(QWidget.setStyleSheet, '_mbt_original'),
                        'QWidget.setStyleSheet is not theme-tracking')
        self.assertTrue(install_style_capture(), 'reinstall must be a no-op')

    def test_theme_hooks_registered(self):
        """Non-stylesheet state (table item roles, painted icons) is hooked."""
        from desktop.utils import theme, widgets  # noqa: F401 — registers hooks
        names = {getattr(fn, '__name__', '') for fn in theme._theme_hooks}
        self.assertIn('_repaint_non_stylesheet_theme_state', names)


class LiveWidgetRestyleTests(unittest.TestCase):
    """End-to-end: real widgets, real theme toggle, no frozen hexes left."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._was_light = ThemeManager.is_light()

    def tearDown(self):
        ThemeManager.apply(self._was_light, force=True)

    @staticmethod
    def _dark_only_hexes():
        light = {v.lower() for v in LIGHT.values() if isinstance(v, str)}
        return {v.lower() for v in DARK.values()
                if isinstance(v, str) and v.lower() not in light}

    def test_dialog_paints_the_surface_colour_in_both_modes(self):
        """A dialog must never fall through to a bare (black) window.

        `QWidget { background: transparent; }` used to be emitted *after*
        `QDialog { background: <surface>; }`.  Both are plain type selectors,
        so they have equal specificity and the later one won under the CSS2
        cascade -- every dialog without its own stylesheet rendered as raw
        black.  This asserts the painted pixel, not the rule order, so any
        future reshuffle of the sheet is caught too.
        """
        from PyQt5.QtGui import QColor, QImage, QPainter
        from PyQt5.QtCore import QPoint
        from PyQt5.QtWidgets import QDialog

        for is_light in (False, True):
            ThemeManager.apply(is_light, force=True)
            dialog = QDialog()
            dialog.resize(120, 80)
            dialog.show()
            self.app.processEvents()

            image = QImage(dialog.size(), QImage.Format_RGB32)
            image.fill(QColor('#FF00FF'))       # a colour in neither palette
            painter = QPainter(image)
            dialog.render(painter, QPoint(0, 0))
            painter.end()

            painted = QColor(image.pixel(4, 4)).name().lower()
            self.assertEqual(
                painted, C['surface'].lower(),
                f'{"light" if is_light else "dark"} dialog painted {painted}, '
                f'expected surface {C["surface"]}')
            dialog.hide()
            dialog.deleteLater()

    def test_no_plain_rule_is_shadowed_by_a_later_base_class_rule(self):
        """Guard the whole sheet against the cascade trap above."""
        from PyQt5 import QtWidgets

        sheet = re.sub(r'/\*.*?\*/', '',
                       ThemeManager.apply(False, force=True), flags=re.S)
        rules = []
        for order, match in enumerate(
                re.finditer(r'([^{}]+)\{([^{}]*)\}', sheet, re.S)):
            declarations = {}
            for part in match.group(2).split(';'):
                if ':' in part:
                    name, _, value = part.partition(':')
                    declarations[name.strip().lower()] = value.strip().lower()
            for selector in match.group(1).split(','):
                selector = selector.strip()
                if re.fullmatch(r'Q[A-Za-z]+', selector):
                    rules.append((order, selector, declarations))

        shadowed = []
        for index, (order, selector, declarations) in enumerate(rules):
            widget_class = getattr(QtWidgets, selector, None)
            if widget_class is None:
                continue
            bases = {base.__name__ for base in widget_class.__mro__}
            for later_order, later, later_decls in rules[index + 1:]:
                if later == selector or later not in bases:
                    continue
                for prop, value in declarations.items():
                    if prop in later_decls and later_decls[prop] != value:
                        shadowed.append(
                            f'{selector}(#{order}) {prop}:{value} lost to '
                            f'{later}(#{later_order}) {prop}:{later_decls[prop]}')
        self.assertEqual(shadowed, [], '; '.join(shadowed))

    def test_visible_label_built_in_dark_repaints_in_light(self):
        from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

        ThemeManager.apply(False, force=True)
        host = QWidget()
        layout = QVBoxLayout(host)
        caption = QLabel('Total sales today')
        caption.setStyleSheet(
            f"color:{C['muted']}; background:{C['card']}; "
            f"border:1px solid {C['border']};")
        layout.addWidget(caption)
        host.show()
        self.app.processEvents()

        ThemeManager.apply(True, force=True)
        sheet = caption.styleSheet().lower()
        leaked = sorted(set(HEX6.findall(sheet)) & self._dark_only_hexes())
        self.assertEqual(leaked, [], f'frozen dark colours in {sheet!r}')
        self.assertIn(LIGHT['muted'].lower(), sheet)
        self.assertIn(LIGHT['card'].lower(), sheet)
        host.hide()
        host.deleteLater()

    def test_hidden_page_repaints_when_it_is_shown(self):
        """A lazily warmed tab is off-screen during the toggle.

        Off-screen widgets are deferred so the toggle stays proportional to
        what is on screen; they must be re-rendered on their next Show, or the
        tab appears in the previous palette.
        """
        from PyQt5.QtWidgets import (QLabel, QStackedWidget, QVBoxLayout,
                                     QWidget)

        ThemeManager.apply(False, force=True)
        host = QWidget()
        layout = QVBoxLayout(host)
        stack = QStackedWidget()
        layout.addWidget(stack)

        front = QLabel('visible page')
        back = QLabel('warmed page')
        back.setStyleSheet(f"color:{C['text2']}; background:{C['card']};")
        stack.addWidget(front)
        stack.addWidget(back)
        host.show()
        self.app.processEvents()
        self.assertFalse(back.isVisibleTo(back.window()))

        ThemeManager.apply(True, force=True)
        self.assertIn(DARK['card'].lower(), back.styleSheet().lower(),
                      'off-screen page should be deferred, not repainted eagerly')

        stack.setCurrentWidget(back)
        host.show()
        self.app.processEvents()

        sheet = back.styleSheet().lower()
        leaked = sorted(set(HEX6.findall(sheet)) & self._dark_only_hexes())
        self.assertEqual(leaked, [], f'off-screen page never repainted: {sheet!r}')
        self.assertIn(LIGHT['text2'].lower(), sheet)
        host.hide()
        host.deleteLater()

    def test_repeated_toggle_is_idempotent(self):
        """Applying the same theme twice must not change any stylesheet."""
        from PyQt5.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

        ThemeManager.apply(True, force=True)
        host = QWidget()
        layout = QVBoxLayout(host)
        lbl = QLabel('caption')
        lbl.setStyleSheet(f"color:{C['muted']}; background:{C['card']};")
        btn = QPushButton('Save')
        btn.setStyleSheet(f"background:{C['gold']}; color:{C['gold_fg']};")
        layout.addWidget(lbl)
        layout.addWidget(btn)
        host.show()
        self.app.processEvents()

        ThemeManager.apply(False, force=True)
        first = (lbl.styleSheet(), btn.styleSheet())
        for _ in range(3):
            ThemeManager.apply(False, force=True)
        self.assertEqual((lbl.styleSheet(), btn.styleSheet()), first)

        ThemeManager.apply(True, force=True)
        ThemeManager.apply(False, force=True)
        self.assertEqual((lbl.styleSheet(), btn.styleSheet()), first,
                         'colours ping-pong across a round trip')
        host.hide()
        host.deleteLater()

    def test_table_item_foregrounds_retint(self):
        from PyQt5.QtWidgets import QTableWidget, QVBoxLayout, QWidget
        from desktop.utils.widgets import tbl_item

        ThemeManager.apply(False, force=True)
        host = QWidget()
        layout = QVBoxLayout(host)
        table = QTableWidget(1, 1)
        table.setItem(0, 0, tbl_item('Sugar 1kg'))
        layout.addWidget(table)
        host.show()
        self.app.processEvents()
        dark_fg = table.item(0, 0).foreground().color().name().lower()

        ThemeManager.apply(True, force=True)
        light_fg = table.item(0, 0).foreground().color().name().lower()
        self.assertNotEqual(dark_fg, light_fg,
                            'frozen QTableWidgetItem foreground')
        self.assertNotIn(light_fg, self._dark_only_hexes())
        host.hide()
        host.deleteLater()


if __name__ == '__main__':
    unittest.main()
