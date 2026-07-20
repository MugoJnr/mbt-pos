"""
MBT POS — Settings → Audio + Audio Diagnostics panels
Theme-aware (Light/Dark via C tokens). Offline.
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox,
    QSlider, QPushButton, QFileDialog, QMessageBox, QScrollArea,
    QFrame, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QTimeEdit, QSpinBox,
)
from PyQt5.QtCore import Qt, QTime, QTimer
from PyQt5.QtGui import QColor

from desktop.utils.theme import C, qss_alpha
from desktop.utils.widgets import section_card, SecondaryBtn, PrimaryBtn, GhostBtn
from desktop.utils.audio_manager import (
    AudioManager, EVENT_META, THEMES, CATEGORIES, get_audio,
)


def _slider_row(label: str, value: float, on_change) -> tuple:
    row = QHBoxLayout()
    lbl = QLabel(label)
    lbl.setStyleSheet(f"color:{C['text']}; font-size:13px; background:transparent;")
    lbl.setMinimumWidth(120)
    sl = QSlider(Qt.Horizontal)
    sl.setRange(0, 100)
    sl.setValue(int(max(0, min(100, value * 100))))
    val = QLabel(f'{sl.value()}%')
    val.setMinimumWidth(40)
    val.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")

    def _chg(v):
        val.setText(f'{v}%')
        on_change(v / 100.0)

    sl.valueChanged.connect(_chg)
    row.addWidget(lbl)
    row.addWidget(sl, 1)
    row.addWidget(val)
    return row, sl


class AudioSettingsPanel(QWidget):
    """Embeddable Audio settings section for SettingsTab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.audio = get_audio()
        self._build()
        self.reload_from_settings()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        # Appearance / Audio main
        grp, body = section_card('*', 'Audio Experience',
                                 'Offline sounds · themes · volumes · collision modes')
        form = QVBoxLayout()
        form.setSpacing(10)

        # Enable + mute
        top = QHBoxLayout()
        self.chk_enabled = QCheckBox('Enable software sounds')
        self.chk_mute = QCheckBox('Mute all')
        self.chk_reduced = QCheckBox('Reduced audio (accessibility)')
        for c in (self.chk_enabled, self.chk_mute, self.chk_reduced):
            c.setStyleSheet(f"color:{C['text']}; font-size:13px;")
            top.addWidget(c)
        top.addStretch(1)
        form.addLayout(top)

        # Theme
        thr = QHBoxLayout()
        tl = QLabel('Sound theme')
        tl.setStyleSheet(f"color:{C['text']}; font-size:13px; background:transparent;")
        self.theme = QComboBox()
        self.theme.setMinimumHeight(36)
        for t in THEMES:
            self.theme.addItem(t.replace('_', ' ').title(), t)
        thr.addWidget(tl)
        thr.addWidget(self.theme, 1)
        form.addLayout(thr)

        # Master volume
        row, self.master_sl = _slider_row('Master volume', 0.75, lambda _: None)
        form.addLayout(row)

        # Modes
        modes = QHBoxLayout()
        self.chk_focus = QCheckBox('Focus Mode (mute nav/UI chrome)')
        self.chk_present = QCheckBox('Presentation Mode (sale/payment/critical only)')
        for c in (self.chk_focus, self.chk_present):
            c.setStyleSheet(f"color:{C['text']}; font-size:13px;")
            modes.addWidget(c)
        modes.addStretch(1)
        form.addLayout(modes)

        # Quiet hours
        qh = QHBoxLayout()
        self.chk_quiet = QCheckBox('Quiet Hours')
        self.chk_quiet.setStyleSheet(f"color:{C['text']}; font-size:13px;")
        self.quiet_start = QTimeEdit()
        self.quiet_end = QTimeEdit()
        for w in (self.quiet_start, self.quiet_end):
            w.setDisplayFormat('HH:mm')
            w.setMinimumHeight(32)
        qh.addWidget(self.chk_quiet)
        qh.addWidget(QLabel('from'))
        qh.addWidget(self.quiet_start)
        qh.addWidget(QLabel('to'))
        qh.addWidget(self.quiet_end)
        qh.addStretch(1)
        form.addLayout(qh)

        # Hardware skip
        hw = QVBoxLayout()
        hw_lbl = QLabel('Hardware already beeps — skip software duplicates:')
        hw_lbl.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
        hw.addWidget(hw_lbl)
        hw_row = QHBoxLayout()
        self.hw_scan = QCheckBox('Scanner')
        self.hw_print = QCheckBox('Printer')
        self.hw_drawer = QCheckBox('Cash drawer')
        self.hw_card = QCheckBox('Card terminal')
        for c in (self.hw_scan, self.hw_print, self.hw_drawer, self.hw_card):
            c.setStyleSheet(f"color:{C['text']}; font-size:12px;")
            hw_row.addWidget(c)
        hw_row.addStretch(1)
        hw.addLayout(hw_row)
        form.addLayout(hw)

        # Category volumes
        cat_lbl = QLabel('Category volumes')
        cat_lbl.setStyleSheet(
            f"color:{C['text']}; font-size:13px; font-weight:700; background:transparent;")
        form.addWidget(cat_lbl)
        self.cat_sliders = {}
        self.cat_mutes = {}
        for cat in CATEGORIES:
            r = QHBoxLayout()
            mute = QCheckBox(f'Mute {cat}')
            mute.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
            self.cat_mutes[cat] = mute
            r.addWidget(mute)
            row, sl = _slider_row(cat.title(), 1.0, lambda _: None)
            self.cat_sliders[cat] = sl
            # flatten row into r
            while row.count():
                item = row.takeAt(0)
                if item.widget():
                    r.addWidget(item.widget())
            form.addLayout(r)

        # Preview + events
        prev = QHBoxLayout()
        self.preview_event = QComboBox()
        self.preview_event.setMinimumHeight(36)
        for ev in sorted(EVENT_META.keys()):
            self.preview_event.addItem(ev, ev)
        btn_prev = SecondaryBtn('Preview sound', 36)
        btn_prev.clicked.connect(self._preview)
        btn_custom = GhostBtn('Replace…', 36)
        btn_custom.clicked.connect(self._replace_custom)
        btn_clear = GhostBtn('Clear custom', 36)
        btn_clear.clicked.connect(self._clear_custom)
        prev.addWidget(self.preview_event, 1)
        prev.addWidget(btn_prev)
        prev.addWidget(btn_custom)
        prev.addWidget(btn_clear)
        form.addLayout(prev)

        # Event enable list (compact)
        ev_lbl = QLabel('Enable / disable events')
        ev_lbl.setStyleSheet(
            f"color:{C['text']}; font-size:13px; font-weight:700; background:transparent;")
        form.addWidget(ev_lbl)
        self.event_checks = {}
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, ev in enumerate(sorted(EVENT_META.keys())):
            cb = QCheckBox(ev)
            cb.setStyleSheet(f"color:{C['text2']}; font-size:11px;")
            self.event_checks[ev] = cb
            grid.addWidget(cb, i // 3, i % 3)
        form.addLayout(grid)

        actions = QHBoxLayout()
        save_btn = PrimaryBtn('Apply Audio Settings', 40)
        save_btn.clicked.connect(self.apply_and_save)
        rst = SecondaryBtn('Restore audio defaults', 40)
        rst.clicked.connect(self._restore)
        actions.addWidget(save_btn)
        actions.addWidget(rst)
        actions.addStretch(1)
        form.addLayout(actions)

        note = QLabel(
            'Critical alerts are never audio-only — messages and dialogs always show. '
            'Sounds are offline WAV/OGG from the app bundle.')
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{C['muted']}; font-size:12px; background:transparent;")
        form.addWidget(note)

        body.addLayout(form)
        root.addWidget(grp)

        # Diagnostics
        dgrp, dbody = section_card('+', 'Audio Diagnostics',
                                   'Pack status, missing files, last events, test each')
        self.diag_theme = QLabel('')
        self.diag_theme.setStyleSheet(f"color:{C['text']}; font-size:13px; background:transparent;")
        self.diag_missing = QLabel('')
        self.diag_missing.setWordWrap(True)
        self.diag_missing.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
        dbody.addWidget(self.diag_theme)
        dbody.addWidget(self.diag_missing)

        self.hist = QTableWidget(0, 4)
        self.hist.setHorizontalHeaderLabels(['Time', 'Event', 'Played', 'Reason'])
        self.hist.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.hist.setMaximumHeight(180)
        self.hist.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hist.setSelectionBehavior(QAbstractItemView.SelectRows)
        dbody.addWidget(self.hist)

        drow = QHBoxLayout()
        ref = SecondaryBtn('Refresh diagnostics', 36)
        ref.clicked.connect(self.refresh_diagnostics)
        test_all = SecondaryBtn('Test all events', 36)
        test_all.clicked.connect(self._test_all)
        drow.addWidget(ref)
        drow.addWidget(test_all)
        drow.addStretch(1)
        dbody.addLayout(drow)
        root.addWidget(dgrp)

        QTimer.singleShot(200, self.refresh_diagnostics)

    def reload_from_settings(self):
        s = self.audio.get_settings()
        self.chk_enabled.setChecked(bool(s.get('enabled', True)))
        self.chk_mute.setChecked(bool(s.get('mute_all')))
        self.chk_reduced.setChecked(bool(s.get('reduced_mode')))
        self.chk_focus.setChecked(bool(s.get('focus_mode')))
        self.chk_present.setChecked(bool(s.get('presentation_mode')))
        self.chk_quiet.setChecked(bool(s.get('quiet_hours_enabled')))
        idx = self.theme.findData(s.get('theme') or 'professional')
        if idx >= 0:
            self.theme.setCurrentIndex(idx)
        self.master_sl.setValue(int(float(s.get('master_volume') or 0.75) * 100))
        for cat, sl in self.cat_sliders.items():
            sl.setValue(int(float((s.get('category_volume') or {}).get(cat, 1.0)) * 100))
        for cat, cb in self.cat_mutes.items():
            cb.setChecked(bool((s.get('category_mute') or {}).get(cat)))
        for ev, cb in self.event_checks.items():
            cb.setChecked(bool((s.get('event_enabled') or {}).get(ev, True)))
        self.hw_scan.setChecked(bool(s.get('hw_scanner_beep')))
        self.hw_print.setChecked(bool(s.get('hw_printer_beep')))
        self.hw_drawer.setChecked(bool(s.get('hw_drawer_beep')))
        self.hw_card.setChecked(bool(s.get('hw_card_beep')))
        try:
            a = (s.get('quiet_hours_start') or '22:00').split(':')
            b = (s.get('quiet_hours_end') or '07:00').split(':')
            self.quiet_start.setTime(QTime(int(a[0]), int(a[1])))
            self.quiet_end.setTime(QTime(int(b[0]), int(b[1])))
        except Exception:
            pass

    def collect_patch(self) -> dict:
        cat_vol = {c: self.cat_sliders[c].value() / 100.0 for c in CATEGORIES}
        cat_mute = {c: self.cat_mutes[c].isChecked() for c in CATEGORIES}
        ev_en = {e: self.event_checks[e].isChecked() for e in EVENT_META}
        return {
            'enabled': self.chk_enabled.isChecked(),
            'mute_all': self.chk_mute.isChecked(),
            'reduced_mode': self.chk_reduced.isChecked(),
            'focus_mode': self.chk_focus.isChecked(),
            'presentation_mode': self.chk_present.isChecked(),
            'quiet_hours_enabled': self.chk_quiet.isChecked(),
            'quiet_hours_start': self.quiet_start.time().toString('HH:mm'),
            'quiet_hours_end': self.quiet_end.time().toString('HH:mm'),
            'theme': self.theme.currentData() or 'professional',
            'master_volume': self.master_sl.value() / 100.0,
            'category_volume': cat_vol,
            'category_mute': cat_mute,
            'event_enabled': ev_en,
            'hw_scanner_beep': self.hw_scan.isChecked(),
            'hw_printer_beep': self.hw_print.isChecked(),
            'hw_drawer_beep': self.hw_drawer.isChecked(),
            'hw_card_beep': self.hw_card.isChecked(),
        }

    def save_silent(self) -> bool:
        ok = self.audio.save_settings(self.collect_patch())
        self.refresh_diagnostics()
        return ok

    def apply_and_save(self):
        ok = self.save_silent()
        if ok:
            self.audio.play('success')
            QMessageBox.information(self, 'Audio', 'Audio settings saved.')
        else:
            QMessageBox.warning(self, 'Audio', 'Could not save audio settings.')

    def _restore(self):
        self.audio.restore_defaults()
        self.reload_from_settings()
        self.refresh_diagnostics()
        QMessageBox.information(self, 'Audio', 'Audio defaults restored.')

    def _preview(self):
        ev = self.preview_event.currentData()
        if ev:
            self.audio.preview(ev)
            self.refresh_diagnostics()

    def _replace_custom(self):
        ev = self.preview_event.currentData()
        if not ev:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, f'Replace sound for {ev}', '',
            'Audio (*.wav *.ogg *.mp3)')
        if path:
            dest = self.audio.set_custom_sound(ev, path)
            if dest:
                QMessageBox.information(self, 'Custom sound', f'Saved custom sound for {ev}.')
                self.refresh_diagnostics()
            else:
                QMessageBox.warning(self, 'Custom sound', 'Failed to copy file.')

    def _clear_custom(self):
        ev = self.preview_event.currentData()
        if ev:
            self.audio.clear_custom_sound(ev)
            self.refresh_diagnostics()

    def refresh_diagnostics(self):
        d = self.audio.diagnostics()
        self.diag_theme.setText(
            f"Theme: {d.get('theme')}  ·  Master: {int(float(d.get('master_volume') or 0)*100)}%  ·  "
            f"Focus: {d.get('focus_mode')}  ·  Presentation: {d.get('presentation_mode')}  ·  "
            f"Quiet active: {(d.get('quiet_hours') or {}).get('active')}")
        miss = d.get('missing') or []
        self.diag_missing.setText(
            f"Present: {len(d.get('present') or [])}  ·  Missing: {len(miss)}"
            + (f" — {', '.join(miss[:12])}" if miss else ' — pack OK'))
        hist = d.get('history') or []
        self.hist.setRowCount(0)
        for h in hist[:20]:
            r = self.hist.rowCount()
            self.hist.insertRow(r)
            self.hist.setItem(r, 0, QTableWidgetItem(str(h.get('t', ''))))
            self.hist.setItem(r, 1, QTableWidgetItem(str(h.get('event', ''))))
            self.hist.setItem(r, 2, QTableWidgetItem('yes' if h.get('played') else 'no'))
            self.hist.setItem(r, 3, QTableWidgetItem(str(h.get('reason', ''))))

    def _test_all(self):
        events = list(EVENT_META.keys())
        self._test_i = 0
        self._test_list = events

        def _next():
            if self._test_i >= len(self._test_list):
                self.refresh_diagnostics()
                return
            ev = self._test_list[self._test_i]
            self._test_i += 1
            self.audio.preview(ev)
            QTimer.singleShot(280, _next)

        _next()
