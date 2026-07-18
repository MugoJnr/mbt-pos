"""MBT POS - Settings | MugoByte Technologies"""
import sys, os, threading, time
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from desktop.utils.theme   import C, MBT_STYLESHEET, qss_alpha
from desktop.utils.widgets import (Card, H2, Caption, PrimaryBtn, SecondaryBtn,
                                    DangerBtn, make_form, FormRow, Field, page_layout,
                                    section_card, page_intro, GhostBtn)

_PR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class SettingsTab(QWidget):
    # Signal fired on main thread when chat ID is found
    _chat_found    = pyqtSignal(str)
    _chat_timeout  = pyqtSignal()
    _chat_error    = pyqtSignal(str)

    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api; self.user = user
        self.db_path = db_path; self.config_getter = config_getter
        self._polling = False
        self._cf_setup_running = False
        self._chat_found.connect(self._on_chat_found)
        self._chat_timeout.connect(self._on_chat_timeout)
        self._chat_error.connect(self._on_chat_error)
        self._build()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        lay, _ = page_layout(self)

        save_top = PrimaryBtn('💾  Save Changes', 40)
        save_top.clicked.connect(self._save)
        intro, _ = page_intro(
            'Settings',
            'Configure your shop, receipts, sync and integrations.',
            save_top)
        lay.addLayout(intro)

        # ── Shop information (Lovable section card) ───────────────────────────
        sg, sf_body = section_card('🏪', 'Shop Information', 'Displayed on receipts and reports')
        sf = make_form(); sf_w = QWidget(); sf_w.setLayout(sf)
        self.shop_name    = Field('Required — shown on receipts and reports')
        self.shop_address = Field('Street or area (optional)')
        self.shop_phone   = Field('+254 700 000 000')
        self.currency     = QComboBox(); self.currency.setMinimumHeight(40)
        for c in ['KES','USD','EUR','GBP','TZS','UGX','ZAR']: self.currency.addItem(c)
        self.tax_rate = QDoubleSpinBox()
        self.tax_rate.setRange(0, 100); self.tax_rate.setDecimals(1)
        self.tax_rate.setSuffix(' %'); self.tax_rate.setMinimumHeight(40)
        for lbl, w in [('Shop Name *', self.shop_name), ('Address', self.shop_address),
                       ('Phone', self.shop_phone), ('Currency', self.currency),
                       ('Tax Rate', self.tax_rate)]:
            FormRow(lbl, w, sf)
        sf_body.addWidget(sf_w)
        lay.addWidget(sg)

        # ── Receipt & printing ────────────────────────────────────────────────
        pg, pf_body = section_card('🖨', 'Receipt Printing', 'Thermal printer and receipt layout')
        pf = make_form(); pf_w = QWidget(); pf_w.setLayout(pf)
        self.receipt_footer = Field('Thank you for shopping with us!')
        self.auto_print = QCheckBox('Auto-print receipt after each sale')
        self.auto_print.setMinimumHeight(36)
        self.printer_port = Field('USB, COM3, or /dev/usb/lp0')
        for lbl, w in [('Receipt Footer', self.receipt_footer),
                       ('', self.auto_print), ('Printer Port', self.printer_port)]:
            FormRow(lbl, w, pf)
        test_btn = SecondaryBtn('Print Test Page', 40)
        test_btn.setFixedWidth(180); test_btn.clicked.connect(self._test_print)
        pf.addRow(QLabel(''), test_btn)
        pf_body.addWidget(pf_w)
        lay.addWidget(pg)

        # ── M-Pesa (per shop — no customer accounts) ───────────────────────────
        mg, mf_body = section_card('📱', 'M-Pesa Payments', 'Till / Paybill shown on receipts')
        mf = make_form(); mf_w = QWidget(); mf_w.setLayout(mf)
        self.mpesa_mode = QComboBox()
        self.mpesa_mode.setMinimumHeight(42)
        self.mpesa_mode.setMinimumWidth(320)
        self.mpesa_mode.addItems(['Manual (Till / Paybill on receipt)', 'STK Push (coming soon)'])
        self.mpesa_mode.model().item(1).setEnabled(False)
        self.mpesa_till = Field('e.g. 123456')
        self.mpesa_paybill = Field('e.g. 400200')
        self.mpesa_business = Field('Name shown on receipt')
        mpesa_hint = QLabel(
            'Each shop uses its own Till or Paybill. Cashiers confirm payment on the customer\'s phone — '
            'no buyer personal details are stored.')
        mpesa_hint.setWordWrap(True)
        mpesa_hint.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
        for lbl, w in [('Mode', self.mpesa_mode), ('Till Number', self.mpesa_till),
                       ('Paybill (optional)', self.mpesa_paybill), ('Business Name', self.mpesa_business)]:
            FormRow(lbl, w, mf)
        mf.addRow(mpesa_hint)
        mf_body.addWidget(mf_w)
        lay.addWidget(mg)

        # ── Payment Variance (M-Pesa / Till excess) ───────────────────────────
        vg, vf_body = section_card('⚖', 'Payment Variance', 'Excess M-Pesa / Till payment handling')
        vf = make_form(); vf_w = QWidget(); vf_w.setLayout(vf)
        self.variance_enabled = QCheckBox('Enable payment variance handling on Till / M-Pesa')
        self.variance_enabled.setMinimumHeight(36)
        self.variance_enable_deposits = QCheckBox('Allow Customer Deposit / Advance (store credit)')
        self.variance_enable_deposits.setMinimumHeight(36)
        self.variance_enable_tips = QCheckBox('Allow Tip allocation')
        self.variance_enable_tips.setMinimumHeight(36)
        self.variance_enable_transport = QCheckBox('Allow Transport / Delivery Fee allocation')
        self.variance_enable_transport.setMinimumHeight(36)
        self.variance_require_customer = QCheckBox('Require customer for deposits and advances')
        self.variance_require_customer.setMinimumHeight(36)
        self.variance_allow_refund = QCheckBox('Allow refunding excess after sale is finalized')
        self.variance_allow_refund.setMinimumHeight(36)
        self.variance_max_cashier = QDoubleSpinBox()
        self.variance_max_cashier.setRange(0, 99999999)
        self.variance_max_cashier.setDecimals(2)
        self.variance_max_cashier.setMinimumHeight(40)
        self.variance_max_cashier.setPrefix('KES ')
        var_hint = QLabel(
            'When Received Amount exceeds the sale total, cashiers must choose how to allocate '
            'the excess (change, deposit, tip, transport, advance, or miscellaneous). '
            'Amounts above the max below require manager / super-admin PIN approval. '
            'Tips and transport are separate revenue — they do not inflate product sales. '
            '“Allow refunding excess after finalize” is a shop policy flag; voiding a sale '
            'always reverses deposits/credit for accounting integrity.')
        var_hint.setWordWrap(True)
        var_hint.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
        FormRow('', self.variance_enabled, vf)
        FormRow('', self.variance_enable_deposits, vf)
        FormRow('', self.variance_enable_tips, vf)
        FormRow('', self.variance_enable_transport, vf)
        FormRow('', self.variance_require_customer, vf)
        FormRow('', self.variance_allow_refund, vf)
        FormRow('Max cashier-approvable variance', self.variance_max_cashier, vf)
        vf.addRow(var_hint)
        vf_body.addWidget(vf_w)
        lay.addWidget(vg)

        # ── Cash Rounding (Sales) ─────────────────────────────────────────────
        from desktop.utils.cash_rounding_service import MODE_LABELS
        cg, cf_body = section_card('🪙', 'Cash Rounding', 'Sales — round final cash amount only')
        cf = make_form(); cf_w = QWidget(); cf_w.setLayout(cf)
        self.cash_rounding_enabled = QCheckBox('Enable cash rounding')
        self.cash_rounding_enabled.setMinimumHeight(36)
        self.cash_rounding_apply_cash = QCheckBox('Apply to Cash')
        self.cash_rounding_apply_cash.setMinimumHeight(36)
        self.cash_rounding_apply_mpesa = QCheckBox('Apply to M-Pesa (not recommended)')
        self.cash_rounding_apply_mpesa.setMinimumHeight(36)
        self.cash_rounding_apply_card = QCheckBox('Apply to Card')
        self.cash_rounding_apply_card.setMinimumHeight(36)
        self.cash_rounding_apply_bank = QCheckBox('Apply to Bank / Cheque / Transfer')
        self.cash_rounding_apply_bank.setMinimumHeight(36)
        self.cash_rounding_mode = QComboBox()
        self.cash_rounding_mode.setMinimumHeight(42)
        self.cash_rounding_mode.setMinimumWidth(280)
        for key, label in MODE_LABELS:
            self.cash_rounding_mode.addItem(label, key)
        self.cash_rounding_value = QDoubleSpinBox()
        self.cash_rounding_value.setRange(1, 1000)
        self.cash_rounding_value.setDecimals(0)
        self.cash_rounding_value.setMinimumHeight(40)
        self.cash_rounding_value.setPrefix('KSh ')
        self.cash_rounding_value.setValue(5)
        round_hint = QLabel(
            'Rounds the final amount due only — product prices never change. '
            'Default: nearest KSh 5 for Cash. M-Pesa, Card, Bank and other electronic '
            'methods stay exact unless you enable them above. '
            'Mixed payments round the cash portion only '
            '(e.g. 137.50 with 100 M-Pesa → cash 37.50 rounds to 40). '
            'Refunds/voids reverse the rounding adjustment and refund the rounded amount paid.')
        round_hint.setWordWrap(True)
        round_hint.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
        FormRow('', self.cash_rounding_enabled, cf)
        FormRow('', self.cash_rounding_apply_cash, cf)
        FormRow('', self.cash_rounding_apply_mpesa, cf)
        FormRow('', self.cash_rounding_apply_card, cf)
        FormRow('', self.cash_rounding_apply_bank, cf)
        FormRow('Rounding Mode', self.cash_rounding_mode, cf)
        FormRow('Rounding Value', self.cash_rounding_value, cf)
        cf.addRow(round_hint)
        cf_body.addWidget(cf_w)
        lay.addWidget(cg)

        # ── Category Visual Settings ───────────────────────────────────────────
        cvg, cv_body = section_card(
            '🎨', 'Category Visual Settings',
            'Offline icons & tiles for POS and inventory')
        cvf = make_form(); cv_w = QWidget(); cv_w.setLayout(cvf)
        from desktop.utils.category_visuals import load_visual_prefs
        _cvp = load_visual_prefs()
        self.cv_tile_size = QSpinBox()
        self.cv_tile_size.setRange(32, 128)
        self.cv_tile_size.setValue(int(_cvp.get('tile_size', 48)))
        self.cv_tile_size.setMinimumHeight(40)
        self.cv_corner = QSpinBox()
        self.cv_corner.setRange(0, 32)
        self.cv_corner.setValue(int(_cvp.get('corner_radius', 12)))
        self.cv_corner.setMinimumHeight(40)
        self.cv_fit = QComboBox()
        self.cv_fit.setMinimumHeight(40)
        self.cv_fit.addItem('Cover (crop to fill)', 'cover')
        self.cv_fit.addItem('Contain (fit inside)', 'contain')
        fi = self.cv_fit.findData(_cvp.get('image_fit', 'cover'))
        if fi >= 0:
            self.cv_fit.setCurrentIndex(fi)
        self.cv_show_labels = QCheckBox('Show labels under tiles')
        self.cv_show_labels.setChecked(bool(_cvp.get('show_labels', True)))
        self.cv_show_accent = QCheckBox('Show accent color ring')
        self.cv_show_accent.setChecked(bool(_cvp.get('show_accent', True)))
        self.cv_compact = QCheckBox('Compact mode (no labels)')
        self.cv_compact.setChecked(bool(_cvp.get('compact_mode', False)))
        self.cv_placeholder = Field('generic/_placeholder.svg')
        self.cv_placeholder.setText(_cvp.get('default_placeholder') or 'generic/_placeholder.svg')
        for lbl, w in [
            ('Tile size (px)', self.cv_tile_size),
            ('Corner radius', self.cv_corner),
            ('Image fit', self.cv_fit),
            ('', self.cv_show_labels),
            ('', self.cv_show_accent),
            ('', self.cv_compact),
            ('Default placeholder', self.cv_placeholder),
        ]:
            FormRow(lbl, w, cvf)
        manage_cats = SecondaryBtn('Manage Category Visuals…', 40)
        manage_cats.clicked.connect(self._open_category_manager)
        cvf.addRow(QLabel(''), manage_cats)
        cv_hint = QLabel(
            'Icons ship with the app (offline). Custom images are stored under AppData uploads/categories/.')
        cv_hint.setWordWrap(True)
        cv_hint.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
        cvf.addRow(cv_hint)
        cv_body.addWidget(cv_w)
        lay.addWidget(cvg)

        # ── Workflow / After Sale defaults ────────────────────────────────────
        wg, wf_body = section_card('🔄', 'Workflow', 'After Sale defaults for POS checkout')
        wform = make_form(); wf_w = QWidget(); wf_w.setLayout(wform)
        self.after_sale_default_customer = QComboBox()
        self.after_sale_default_customer.setMinimumHeight(42)
        self.after_sale_default_customer.addItem('Walk-in Customer', 'walk_in')
        self.after_sale_default_payment = QComboBox()
        self.after_sale_default_payment.setMinimumHeight(42)
        from desktop.utils.option_lists import POS_PAYMENT_METHODS
        self.after_sale_default_payment.addItems(list(POS_PAYMENT_METHODS))
        self.after_sale_focus_barcode = QCheckBox('Focus barcode / search after each sale')
        self.after_sale_focus_barcode.setMinimumHeight(36)
        self.after_sale_auto_clear_cart = QCheckBox('Auto-clear cart after successful sale')
        self.after_sale_auto_clear_cart.setMinimumHeight(36)
        self.after_sale_reset_discounts = QCheckBox('Reset discounts after sale')
        self.after_sale_reset_discounts.setMinimumHeight(36)
        self.after_sale_reset_notes = QCheckBox('Reset notes after sale')
        self.after_sale_reset_notes.setMinimumHeight(36)
        self.autofill_cash_paid = QCheckBox(
            'Auto-fill Cash Paid = Amount Due (after discount / tax / rounding)')
        self.autofill_cash_paid.setMinimumHeight(36)
        self.autofill_product_defaults = QCheckBox(
            'Product create defaults (unit, min stock alert, Active)')
        self.autofill_product_defaults.setMinimumHeight(36)
        self.autofill_reports_today = QCheckBox('Reports default date range: Today')
        self.autofill_reports_today.setMinimumHeight(36)
        self.autofill_clear_search_on_leave = QCheckBox(
            'Clear module search when leaving a tab')
        self.autofill_clear_search_on_leave.setMinimumHeight(36)
        self.autofill_credit_customer_info = QCheckBox(
            'Show credit customer balance / limit when selected')
        self.autofill_credit_customer_info.setMinimumHeight(36)
        wf_hint = QLabel(
            'After every successful sale (Cash, M-Pesa, Credit, split), POS restores these '
            'defaults. Customer always returns to Walk-in so a credit sale for John Kamau '
            'never leaves John selected on the next ticket. '
            'Cash Paid re-fills on the next sale until the cashier edits it; switching '
            'back to Cash resets that lock. Notes, void/consumption reasons, and '
            'discretionary discounts are never auto-filled.')
        wf_hint.setWordWrap(True)
        wf_hint.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
        FormRow('Default customer', self.after_sale_default_customer, wform)
        FormRow('Default payment', self.after_sale_default_payment, wform)
        FormRow('', self.after_sale_focus_barcode, wform)
        FormRow('', self.after_sale_auto_clear_cart, wform)
        FormRow('', self.after_sale_reset_discounts, wform)
        FormRow('', self.after_sale_reset_notes, wform)
        FormRow('', self.autofill_cash_paid, wform)
        FormRow('', self.autofill_product_defaults, wform)
        FormRow('', self.autofill_reports_today, wform)
        FormRow('', self.autofill_clear_search_on_leave, wform)
        FormRow('', self.autofill_credit_customer_info, wform)
        wform.addRow(wf_hint)
        wf_body.addWidget(wf_w)
        lay.addWidget(wg)

        # ── Automatic reports ─────────────────────────────────────────────────
        rg, rf_body = section_card('📊', 'Automatic Telegram Reports', 'Auto-schedule daily reports')
        rf = make_form(); rf_w = QWidget(); rf_w.setLayout(rf)
        self.auto_report_daily = QCheckBox('Send daily sales report (Excel) to Telegram')
        self.auto_report_daily.setMinimumHeight(36)
        self.auto_report_weekly = QCheckBox('Also send weekly summary (last 7 days)')
        self.auto_report_weekly.setMinimumHeight(36)
        self.auto_db_backup = QCheckBox(
            'Send daily database backup to Telegram (disaster recovery)')
        self.auto_db_backup.setMinimumHeight(36)
        rep_hint = QLabel(
            'Requires Telegram connected below. One daily Excel report per shop per date '
            '(queued offline, sent when online, catch-up for missed days). '
            'Database backups go to your Telegram and the developer copy once every 24 hours.')
        rep_hint.setWordWrap(True)
        rep_hint.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
        FormRow('', self.auto_report_daily, rf)
        FormRow('', self.auto_report_weekly, rf)
        FormRow('', self.auto_db_backup, rf)
        try:
            from backend.local_db_backup import local_backup_status, get_local_backup_dir
            st = local_backup_status()
            self._local_bak_lbl = QLabel(
                f"Local auto-backup: {st.get('last_at') or 'pending'} · {get_local_backup_dir()}")
            self._local_bak_lbl.setWordWrap(True)
            self._local_bak_lbl.setStyleSheet(f"color:{C['text2']};font-size:12px;background:transparent;")
            FormRow('', self._local_bak_lbl, rf)
        except Exception:
            pass

        rf.addRow(rep_hint)
        self._send_report_now_btn = SecondaryBtn('Send Today\'s Report Now', 40)
        self._send_report_now_btn.clicked.connect(self._send_report_now)
        rf.addRow(QLabel(''), self._send_report_now_btn)
        self._send_backup_now_btn = SecondaryBtn('Send Database Backup Now', 40)
        self._send_backup_now_btn.clicked.connect(self._send_backup_now)
        rf.addRow(QLabel(''), self._send_backup_now_btn)
        rf_body.addWidget(rf_w)
        lay.addWidget(rg)

        # ── Telegram notifications ─────────────────────────────────────────────
        tg, tg_body = section_card('💬', 'Telegram Notifications', 'Connect bot for reports and keys')
        _tg_lay = QVBoxLayout(); _tg_lay.setContentsMargins(0, 0, 0, 0); _tg_lay.setSpacing(14)

        # Status row — shows whether Telegram is connected or not
        self._tg_status_row = QFrame()
        self._tg_status_row.setStyleSheet(
            f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};"
            f"border-radius:10px;padding:0;}}")
        sr = QHBoxLayout(self._tg_status_row)
        sr.setContentsMargins(16, 12, 16, 12); sr.setSpacing(12)
        self._tg_icon  = QLabel('○')
        self._tg_icon.setStyleSheet("font-size:22px; background:transparent;")
        self._tg_title = QLabel('Telegram not connected')
        self._tg_title.setStyleSheet(
            f"color:{C['text']}; font-size:14px; font-weight:700; background:transparent;")
        self._tg_sub   = QLabel('Connect to receive reports and license keys via Telegram.')
        self._tg_sub.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent;")
        sc = QVBoxLayout(); sc.setSpacing(2)
        sc.addWidget(self._tg_title); sc.addWidget(self._tg_sub)
        sr.addWidget(self._tg_icon); sr.addLayout(sc, 1)
        _tg_lay.addWidget(self._tg_status_row)

        # Step card — how to connect
        step_card = QFrame()
        step_card.setStyleSheet(
            f"QFrame{{background:{C['card']};border:1px solid {C['border2']};"
            f"border-radius:10px;}}")
        sl = QVBoxLayout(step_card)
        sl.setContentsMargins(18, 14, 18, 14); sl.setSpacing(10)

        how_lbl = QLabel('HOW TO CONNECT')
        how_lbl.setStyleSheet(
            f"color:{C['muted']}; font-size:10px; font-weight:700; "
            f"letter-spacing:1.5px; background:transparent;")
        sl.addWidget(how_lbl)

        steps_lbl = QLabel(
            '1.  Open Telegram on your phone or PC\n'
            '2.  Search for  <b>@mbt_admin1_bot</b>  and tap Start\n'
            '3.  Send any message (e.g. "Hello")\n'
            '4.  Click  <b>Connect My Telegram</b>  below — done!'
        )
        self._steps_lbl = steps_lbl
        steps_lbl.setTextFormat(Qt.RichText)
        steps_lbl.setStyleSheet(
            f"color:{C['text2']}; font-size:13px; line-height:1.6; background:transparent;")
        sl.addWidget(steps_lbl)

        # Connect button row
        btn_row = QHBoxLayout(); btn_row.setSpacing(10)
        self._connect_btn = PrimaryBtn('📲  Connect My Telegram', 44)
        self._connect_btn.clicked.connect(self._start_connect)

        self._disconnect_btn = SecondaryBtn('Disconnect', 44)
        self._disconnect_btn.clicked.connect(self._disconnect)
        self._disconnect_btn.hide()

        self._test_tg_btn = SecondaryBtn('✉  Send Test Message', 44)
        self._test_tg_btn.clicked.connect(self._test_tg)
        self._test_tg_btn.hide()

        btn_row.addWidget(self._connect_btn)
        btn_row.addWidget(self._test_tg_btn)
        btn_row.addWidget(self._disconnect_btn)
        btn_row.addStretch()
        sl.addLayout(btn_row)

        # Progress / feedback label (hidden until connecting)
        self._tg_progress = QLabel('')
        self._tg_progress.setStyleSheet(
            f"color:{C['warn']}; font-size:12px; background:transparent;")
        self._tg_progress.hide()
        sl.addWidget(self._tg_progress)

        _tg_lay.addWidget(step_card)

        # Hidden field — stores the chat ID internally, not shown to user
        self.tg_chat     = QLineEdit(); self.tg_chat.hide()
        self.dev_chat    = QLineEdit(); self.dev_chat.hide()
        self.tg_token    = QLineEdit(); self.tg_token.hide()
        self.sync_interval = QSpinBox(); self.sync_interval.hide()
        _tg_lay.addWidget(self.tg_chat)
        _tg_lay.addWidget(self.dev_chat)
        _tg_lay.addWidget(self.tg_token)
        _tg_lay.addWidget(self.sync_interval)
        tg_body.addLayout(_tg_lay)
        lay.addWidget(tg)

        # ── Remote web dashboard (Cloudflare) ─────────────────────────────────
        wg, wg_body = section_card('☁', 'Remote Web Dashboard', 'Sync sales and inventory to the cloud')
        _wg_lay = QVBoxLayout(); _wg_lay.setContentsMargins(0, 0, 0, 0); _wg_lay.setSpacing(14)

        self._cf_status_row = QFrame()
        self._cf_status_row.setStyleSheet(
            f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};"
            f"border-radius:10px;}}")
        csr = QHBoxLayout(self._cf_status_row)
        csr.setContentsMargins(16, 12, 16, 12)
        self._cf_icon = QLabel('○')
        self._cf_icon.setStyleSheet("font-size:22px; background:transparent;")
        self._cf_title = QLabel('Remote dashboard not configured')
        self._cf_title.setStyleSheet(
            f"color:{C['text']}; font-size:14px; font-weight:700; background:transparent;")
        self._cf_sub = QLabel(
            'View sales and inventory from anywhere via your mugobyte.com link.')
        self._cf_sub.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent;")
        self._cf_sub.setWordWrap(True)
        csc = QVBoxLayout()
        csc.addWidget(self._cf_title)
        csc.addWidget(self._cf_sub)
        csr.addWidget(self._cf_icon)
        csr.addLayout(csc, 1)
        _wg_lay.addWidget(self._cf_status_row)

        hint = QLabel(
            'Local access on the same Wi‑Fi works without setup: '
            '<b>http://&lt;shop-pc-ip&gt;:5050</b><br>'
            'Remote URL is set once at install from the <b>shop name</b> '
            '(e.g. “Edmus” → <b>edmus.mugobyte.com</b>). Do not change after go-live.')
        hint.setTextFormat(Qt.RichText)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
        _wg_lay.addWidget(hint)

        self._cf_mode_lan = QRadioButton('LAN only — no Cloudflare setup needed')
        self._cf_mode_remote = QRadioButton('Remote access — https://<shop>.mugobyte.com')
        self._cf_mode_lan.setChecked(True)
        for rb in (self._cf_mode_lan, self._cf_mode_remote):
            rb.setStyleSheet(f"color:{C['text']}; font-size:14px;")
            _wg_lay.addWidget(rb)

        remote_box = QFrame()
        remote_box.setStyleSheet(
            f"QFrame{{background:{C['card']};border:1px solid {C['border2']};border-radius:10px;}}")
        rbl = QVBoxLayout(remote_box)
        rbl.setContentsMargins(16, 14, 16, 14)
        rbl.setSpacing(10)

        sub_form = QFormLayout()
        sub_form.setSpacing(10)
        self._cf_subdomain = QLabel('—')
        self._cf_subdomain.setStyleSheet(
            f"color:{C['text']}; font-size:14px; font-weight:600; background:transparent;")
        sub_lbl = QLabel('Remote URL (from shop name)')
        sub_lbl.setStyleSheet(f"color:{C['text2']}; font-size:14px;")
        sub_form.addRow(sub_lbl, self._cf_subdomain)
        prod_note = QLabel(
            'Set during first install. Each shop gets one permanent link. '
            'MBT POS sets fast DNS on this PC automatically during Cloudflare setup.')
        prod_note.setWordWrap(True)
        prod_note.setStyleSheet(f"color:{C['muted']}; font-size:11px; background:transparent;")
        rbl.addWidget(prod_note)
        rbl.addLayout(sub_form)

        self._cf_preview = QLabel('https://….mugobyte.com')
        self._cf_preview.setStyleSheet(
            f"color:{C['gold']}; font-size:15px; font-weight:700; font-family:Consolas;")
        rbl.addWidget(self._cf_preview)

        self.shop_name.textChanged.connect(self._update_cf_preview)

        cf_btn_row = QHBoxLayout()
        self._cf_setup_btn = PrimaryBtn('Set Up Cloudflare', 40)
        self._cf_setup_btn.clicked.connect(self._cf_setup_or_fix)
        self._cf_test_btn = SecondaryBtn('Test Connection', 40)
        self._cf_test_btn.clicked.connect(self._test_cloudflare)
        self._cf_repair_btn = SecondaryBtn('Repair', 40)
        self._cf_repair_btn.setToolTip(
            'Reconcile DNS/ingress, re-check HTTPS, drain retry queue. No browser login.')
        self._cf_repair_btn.clicked.connect(self._repair_cloudflare)
        self._cf_relogin_btn = SecondaryBtn('Vendor recovery', 40)
        self._cf_relogin_btn.setToolTip(
            'Emergency only — browser login to Cloudflare. '
            'Normal shops use the central API token automatically.')
        self._cf_relogin_btn.clicked.connect(lambda: self._run_cloudflare_setup(True))
        cf_btn_row.addWidget(self._cf_setup_btn)
        cf_btn_row.addWidget(self._cf_test_btn)
        cf_btn_row.addWidget(self._cf_repair_btn)
        cf_btn_row.addWidget(self._cf_relogin_btn)
        cf_btn_row.addStretch()
        rbl.addLayout(cf_btn_row)

        self._cf_health = QLabel('')
        self._cf_health.setWordWrap(True)
        self._cf_health.setStyleSheet(
            f"color:{C['muted']}; font-size:11px; font-family:Consolas; background:transparent;")
        rbl.addWidget(self._cf_health)

        self._cf_status = QLabel(
            'Remote access auto-provisions on launch when the vendor API token is installed.')
        self._cf_status.setWordWrap(True)
        self._cf_status.setStyleSheet(f"color:{C['text2']}; font-size:13px;")
        rbl.addWidget(self._cf_status)

        self._cf_log = QTextEdit()
        self._cf_log.setReadOnly(True)
        self._cf_log.setMinimumHeight(100)
        self._cf_log.setPlaceholderText('Setup log appears here…')
        self._cf_log.setStyleSheet(
            f"background:{C['surface']}; color:{C['text2']}; font-family:Consolas; font-size:11px;")
        rbl.addWidget(self._cf_log)

        _wg_lay.addWidget(remote_box)
        self._cf_remote_box = remote_box
        self._cf_mode_lan.toggled.connect(self._toggle_cf_remote_box)
        self._cf_mode_remote.toggled.connect(self._toggle_cf_remote_box)
        wg_body.addLayout(_wg_lay)
        lay.addWidget(wg)

        # ── MBT Cloud Backup (Supabase encrypted snapshots) ───────────────────
        try:
            from desktop.tabs.cloud_backup_panel import CloudBackupPanel
            self._cloud_panel = CloudBackupPanel(self)
            lay.addWidget(self._cloud_panel)
        except Exception as _ce:
            self._cloud_panel = None

        # ── Audio Experience (offline themes + collision modes) ───────────────
        try:
            from desktop.tabs.audio_settings_panel import AudioSettingsPanel
            self._audio_panel = AudioSettingsPanel(self)
            lay.addWidget(self._audio_panel)
        except Exception as _ae:
            self._audio_panel = None

        role = self.user.get('user', {}).get('role', '')
        if role in ('admin', 'superadmin'):
            lay.addWidget(SecuritySettingsTab(self.api, self.user, self.config_getter))
            vg, vg_body = section_card('🚫', 'Void Completed Sale', 'Cancel a sale by receipt number')
            vinfo = QLabel(
                'Cancel a completed sale by receipt number. Stock is restored automatically.\n'
                'Pick a standardized void reason (Other requires specify). Requires Super-Admin PIN.\n'
                'Also available from Point of Sale (Void Sale) and Dashboard → Recent Sales.')
            vinfo.setWordWrap(True)
            vinfo.setStyleSheet(
                f"color:{C['text2']}; font-size:13px; background:transparent;")
            vg_body.addWidget(vinfo)
            vrow = QHBoxLayout()
            self._void_receipt = Field('Receipt number  e.g. RCP-20260605-0089')
            self._void_receipt.setMinimumHeight(42)
            void_btn = DangerBtn('Void Sale', 42)
            void_btn.clicked.connect(self._void_sale)
            vrow.addWidget(self._void_receipt, 1)
            vrow.addWidget(void_btn)
            vg_body.addLayout(vrow)
            lay.addWidget(vg)

        # ── Save ──────────────────────────────────────────────────────────────
        save = PrimaryBtn('Save All Settings', 50)
        save.clicked.connect(self._save); lay.addWidget(save)

        rst = QPushButton('Reset Setup Wizard')
        rst.setStyleSheet(
            f"background:transparent; color:{C['text']}; "
            f"border:1px solid {C['border2']}; border-radius:8px; "
            f"padding:10px 18px; font-size:13px; font-weight:600;")
        rst.setCursor(Qt.PointingHandCursor); rst.clicked.connect(self._reset_wiz)
        lay.addWidget(rst)

        foot = Caption('MBT POS  ·  Powered by MugoByte Technologies  ·  mugobyte.com')
        foot.setAlignment(Qt.AlignCenter); lay.addWidget(foot)

    # ── Data ──────────────────────────────────────────────────────────────────

    def on_show(self): self.refresh()

    def refresh(self):
        cfg = self.api.get_settings() or {}
        deploy = {}
        bot_user = 'mbt_admin1_bot'
        tok = cfg.get('telegram_bot_token', '')
        try:
            from config.deploy import load_deploy_config
            from backend.telegram_hub import resolve_bot_token, resolve_bot_username
            deploy = load_deploy_config()
            bot_user = resolve_bot_username(cfg)
            self._bot_username = bot_user
            tok = resolve_bot_token(cfg) or tok
        except Exception:
            self._bot_username = bot_user

        if tok and not cfg.get('telegram_bot_token'):
            self.tg_token.setText(tok)
        elif cfg.get('telegram_bot_token'):
            self.tg_token.setText(cfg.get('telegram_bot_token', ''))
        elif deploy.get('telegram_bot_token'):
            self.tg_token.setText(deploy.get('telegram_bot_token', ''))

        # Update connect instructions with the configured bot name
        if hasattr(self, '_steps_lbl'):
            self._steps_lbl.setText(
                '1.  Open Telegram on your phone or PC\n'
                f'2.  Search for  <b>@{bot_user}</b>  and tap Start\n'
                '3.  Send any message (e.g. "Hello")\n'
                '4.  Click  <b>Connect My Telegram</b>  below — done!'
            )
        self.shop_name.setText(cfg.get('shop_name', ''))
        self.shop_address.setText(cfg.get('shop_address', ''))
        self.shop_phone.setText(cfg.get('shop_phone', ''))
        idx = self.currency.findText(cfg.get('currency_symbol', 'KES'))
        if idx >= 0: self.currency.setCurrentIndex(idx)
        self.tax_rate.setValue(float(cfg.get('tax_rate', 0) or 0))
        self.receipt_footer.setText(cfg.get('receipt_footer', 'Thank you for shopping with us!'))
        self.auto_print.setChecked(cfg.get('auto_print', '1') == '1')
        self.printer_port.setText(cfg.get('printer_port', ''))
        if not self.tg_token.text().strip():
            self.tg_token.setText(tok or cfg.get('telegram_bot_token', ''))
        self.tg_chat.setText(cfg.get('telegram_chat_id', ''))
        dev = cfg.get('developer_chat_id', '') or deploy.get('developer_chat_id', '')
        self.dev_chat.setText(str(dev))
        self.sync_interval.setValue(int(cfg.get('sync_interval', 30) or 30))
        self.mpesa_till.setText(cfg.get('mpesa_till', ''))
        self.mpesa_paybill.setText(cfg.get('mpesa_paybill', ''))
        self.mpesa_business.setText(cfg.get('mpesa_business_name', '') or cfg.get('shop_name', ''))
        mode = cfg.get('mpesa_mode', 'manual')
        self.mpesa_mode.setCurrentIndex(1 if mode == 'stk' else 0)
        self.auto_report_daily.setChecked(cfg.get('auto_report_daily', '1') == '1')
        self.auto_report_weekly.setChecked(cfg.get('auto_report_weekly', '0') == '1')
        self.auto_db_backup.setChecked(cfg.get('auto_db_backup', '1') == '1')
        if hasattr(self, 'variance_enabled'):
            self.variance_enabled.setChecked(cfg.get('variance_enabled', '1') == '1')
            self.variance_enable_deposits.setChecked(
                cfg.get('variance_enable_deposits', '1') == '1')
            self.variance_enable_tips.setChecked(cfg.get('variance_enable_tips', '1') == '1')
            self.variance_enable_transport.setChecked(
                cfg.get('variance_enable_transport', '1') == '1')
            self.variance_require_customer.setChecked(
                cfg.get('variance_require_customer_deposit', '1') == '1')
            self.variance_allow_refund.setChecked(
                cfg.get('variance_allow_refund_after_finalize', '0') == '1')
            try:
                self.variance_max_cashier.setValue(
                    float(cfg.get('variance_max_cashier', 1000) or 1000))
            except (TypeError, ValueError):
                self.variance_max_cashier.setValue(1000)
        if hasattr(self, 'cash_rounding_enabled'):
            self.cash_rounding_enabled.setChecked(
                cfg.get('cash_rounding_enabled', '1') == '1')
            self.cash_rounding_apply_cash.setChecked(
                cfg.get('cash_rounding_apply_cash', '1') == '1')
            self.cash_rounding_apply_mpesa.setChecked(
                cfg.get('cash_rounding_apply_mpesa', '0') == '1')
            self.cash_rounding_apply_card.setChecked(
                cfg.get('cash_rounding_apply_card', '0') == '1')
            self.cash_rounding_apply_bank.setChecked(
                cfg.get('cash_rounding_apply_bank', '0') == '1')
            mode = (cfg.get('cash_rounding_mode') or 'nearest').strip().lower()
            idx = self.cash_rounding_mode.findData(mode)
            self.cash_rounding_mode.setCurrentIndex(idx if idx >= 0 else 0)
            try:
                self.cash_rounding_value.setValue(
                    float(cfg.get('cash_rounding_value', 5) or 5))
            except (TypeError, ValueError):
                self.cash_rounding_value.setValue(5)
        if hasattr(self, 'after_sale_default_customer'):
            cust = (cfg.get('after_sale_default_customer') or 'walk_in').strip().lower()
            cidx = self.after_sale_default_customer.findData(cust)
            self.after_sale_default_customer.setCurrentIndex(cidx if cidx >= 0 else 0)
            pay = (cfg.get('after_sale_default_payment') or 'Cash').strip()
            pidx = self.after_sale_default_payment.findText(pay)
            self.after_sale_default_payment.setCurrentIndex(pidx if pidx >= 0 else 0)
            self.after_sale_focus_barcode.setChecked(
                cfg.get('after_sale_focus_barcode', '1') == '1')
            self.after_sale_auto_clear_cart.setChecked(
                cfg.get('after_sale_auto_clear_cart', '1') == '1')
            self.after_sale_reset_discounts.setChecked(
                cfg.get('after_sale_reset_discounts', '1') == '1')
            self.after_sale_reset_notes.setChecked(
                cfg.get('after_sale_reset_notes', '1') == '1')
        if hasattr(self, 'autofill_cash_paid'):
            self.autofill_cash_paid.setChecked(
                cfg.get('autofill_cash_paid', '1') == '1')
            self.autofill_product_defaults.setChecked(
                cfg.get('autofill_product_defaults', '1') == '1')
            self.autofill_reports_today.setChecked(
                cfg.get('autofill_reports_today', '1') == '1')
            self.autofill_clear_search_on_leave.setChecked(
                cfg.get('autofill_clear_search_on_leave', '1') == '1')
            self.autofill_credit_customer_info.setChecked(
                cfg.get('autofill_credit_customer_info', '1') == '1')
        self._refresh_tg_status()
        self._refresh_report_health()
        self._refresh_cf_status()
        self._refresh_cf_health_panel()
        panel = getattr(self, '_cloud_panel', None)
        if panel is not None:
            try:
                panel.refresh()
            except Exception:
                pass

    def _refresh_cf_health_panel(self):
        """Admin diagnostic strip — token/zone/DNS/SSL (no secrets)."""
        if not hasattr(self, '_cf_health'):
            return
        try:
            from backend.cloudflare_setup import get_cloudflare_health_panel
            p = get_cloudflare_health_panel()
            lines = [
                f"State: {p.get('connection_state')}  ·  Token: {p.get('token_type')} "
                f"({'valid' if p.get('token_valid') else 'check'})",
                f"Zone: {p.get('zone_detail') or '—'}  ·  DNS: "
                f"{'OK' if p.get('dns_ok') else 'FAIL'}  ·  SSL: "
                f"{'OK' if p.get('ssl_ok') else 'FAIL'}",
                f"Tunnel: {'up' if p.get('tunnel_running') else 'down'}  ·  "
                f"Queue: {p.get('retry_queue_len', 0)}  ·  "
                f"Err: {p.get('last_error') or '—'}",
            ]
            self._cf_health.setText('\n'.join(lines))
        except Exception as e:
            self._cf_health.setText(f'Health panel unavailable: {e}')

    def _repair_cloudflare(self):
        if not self._require_cf_admin():
            return
        self._cf_status.setText('⏳ Repairing Cloudflare (DNS/ingress/HTTPS)…')
        self._cf_repair_btn.setEnabled(False)

        def _cb(level, msg):
            QTimer.singleShot(0, lambda l=level, m=msg: self._cf_log_append(l, m))

        def worker():
            try:
                from backend.cloudflare_setup import (
                    reconcile_cloudflare_state, process_cf_retry_queue, _SetupLog,
                )
                log = _SetupLog(_cb)
                rep = reconcile_cloudflare_state(
                    force_dns=True, verify_https=True, log=log)
                process_cf_retry_queue(max_items=3)
                QTimer.singleShot(0, lambda: self._on_cf_repair_done(rep))
            except Exception as e:
                QTimer.singleShot(0, lambda: self._on_cf_repair_done(
                    {'ok': False, 'errors': [str(e)], 'active': False}))

        threading.Thread(target=worker, daemon=True, name='CF-Repair').start()

    def _on_cf_repair_done(self, rep: dict):
        if hasattr(self, '_cf_repair_btn'):
            self._cf_repair_btn.setEnabled(True)
        if rep.get('active'):
            self._cf_status.setText('✓ Repair OK — remote ACTIVE')
            self._cf_status.setStyleSheet(
                f"color:{C['ok']}; font-size:13px; font-weight:600;")
        elif rep.get('ok'):
            self._cf_status.setText(
                'Repair ran — still pending DNS/HTTPS (not ACTIVE yet).')
            self._cf_status.setStyleSheet(
                f"color:{C['warn']}; font-size:13px; font-weight:600;")
        else:
            errs = '; '.join(rep.get('errors') or ['repair failed'])[:200]
            self._cf_status.setText(f'✗ Repair: {errs}')
            self._cf_status.setStyleSheet(
                f"color:{C['err']}; font-size:13px; font-weight:600;")
        self._refresh_cf_status()
        self._refresh_cf_health_panel()

    def _refresh_report_health(self):
        """Update Automatic Reports health panel (no secrets)."""
        if not hasattr(self, '_rh_connected'):
            return
        try:
            from backend.telegram_reporter import get_report_health
            h = get_report_health(self.config_getter)
        except Exception as e:
            self._rh_connected.setText(f'Connected: error ({e})')
            self._rh_sched.setText('Scheduler: —')
            return

        connected = h.get('telegram_connected')
        hub = h.get('hub_state') or ''
        warn = h.get('config_warnings') or []
        if connected:
            self._rh_connected.setText(
                f'Connected: Yes  ·  Hub: {hub or "ok"}')
            self._rh_connected.setStyleSheet(
                f"color:{C['ok']}; font-size:12px; background:transparent;")
        else:
            tip = warn[0] if warn else 'Connect Telegram below'
            self._rh_connected.setText(f'Connected: No — {tip}')
            self._rh_connected.setStyleSheet(
                f"color:{C['warn']}; font-size:12px; background:transparent;")

        last_date = h.get('last_report_date') or 'never'
        last_st = h.get('last_report_status') or 'none'
        sent_at = h.get('last_sent_at') or ''
        self._rh_last.setText(
            f'Last Report: {last_date} ({last_st})'
            + (f'  ·  {sent_at}' if sent_at else '')
        )

        pending = h.get('delivery_pending', 0)
        failed = h.get('delivery_failed', 0)
        self._rh_delivery.setText(
            f'Delivery: {pending} pending / retrying  ·  {failed} failed'
        )
        self._rh_failed.setText(
            f"Failed Attempts: {h.get('failed_attempts', 0)}"
        )

        sched = h.get('scheduler') or 'STOPPED'
        detail = h.get('scheduler_detail') or ''
        self._rh_sched.setText(f'Scheduler: {sched}' + (f'  ·  {detail}' if detail else ''))
        if sched == 'RUNNING':
            self._rh_sched.setStyleSheet(
                f"color:{C['ok']}; font-size:12px; background:transparent;")
        else:
            self._rh_sched.setStyleSheet(
                f"color:{C['text2']}; font-size:12px; background:transparent;")

    def _refresh_cf_status(self):
        try:
            from backend.cloudflare_setup import (
                load_web_config, shop_to_subdomain, full_domain,
                refresh_remote_setup_status,
            )
            # Never block the UI thread on network/DNS during tab show
            try:
                import threading
                threading.Thread(
                    target=refresh_remote_setup_status, daemon=True,
                    name='CFStatusRefresh').start()
            except Exception:
                pass
            wcfg = load_web_config()
        except Exception:
            wcfg = {}
        remote = bool(wcfg.get('remote_enabled'))
        domain = wcfg.get('tunnel_domain', '')
        setup_ok = bool(wcfg.get('remote_setup_ok'))
        self._cf_mode_remote.setChecked(remote)
        self._cf_mode_lan.setChecked(not remote)
        sub = wcfg.get('tunnel_subdomain', '')
        shop_slug = self._production_subdomain()
        if shop_slug:
            self._cf_subdomain.setText(shop_slug)
        elif sub:
            self._cf_subdomain.setText(sub)
        self._toggle_cf_remote_box()
        self._update_cf_preview()
        if remote and domain and setup_ok:
            self._cf_icon.setText('✓')
            self._cf_icon.setStyleSheet(f"font-size:22px; color:{C['ok']}; background:transparent;")
            self._cf_title.setText('Remote dashboard ACTIVE')
            self._cf_title.setStyleSheet(
                f"color:{C['ok']}; font-size:14px; font-weight:700; background:transparent;")
            self._cf_sub.setText(f'https://{domain}  ·  Keep MBT POS running for remote access.')
            self._cf_status_row.setStyleSheet(
                f"QFrame{{background:{C['ok_dim']};border:1px solid {qss_alpha(C['ok'], 0.25)};border-radius:10px;}}")
            self._cf_status.setText('ACTIVE — DNS + HTTPS verified. Tunnel auto-starts on launch.')
            self._cf_setup_btn.setText('Repair / Re-check')
        else:
            # Prefer live status helper when available
            st = {}
            try:
                from backend.cloudflare_setup import get_remote_dashboard_status
                st = get_remote_dashboard_status()
            except Exception:
                st = {}
            state = st.get('state') or (
                'configured' if (remote and domain) else 'needs_setup')
            detail = st.get('detail') or (
                f'https://{domain} — finish one-time setup' if domain else
                'View sales and inventory from anywhere via your mugobyte.com link.')
            if state == 'active':
                self._cf_icon.setText('✓')
                self._cf_icon.setStyleSheet(f"font-size:22px; color:{C['ok']}; background:transparent;")
                self._cf_title.setText('Remote dashboard ACTIVE')
                self._cf_title.setStyleSheet(
                    f"color:{C['ok']}; font-size:14px; font-weight:700; background:transparent;")
                self._cf_sub.setText(detail)
                self._cf_status_row.setStyleSheet(
                    f"QFrame{{background:{C['ok_dim']};border:1px solid {qss_alpha(C['ok'], 0.25)};border-radius:10px;}}")
                self._cf_status.setText('ACTIVE — DNS + HTTPS verified.')
                self._cf_setup_btn.setText('Repair / Re-check')
            elif state == 'pending':
                self._cf_icon.setText('◐')
                self._cf_icon.setStyleSheet(f"font-size:22px; color:{C['warn']}; background:transparent;")
                self._cf_title.setText('Remote pending DNS/HTTPS')
                self._cf_title.setStyleSheet(
                    f"color:{C['warn']}; font-size:14px; font-weight:700; background:transparent;")
                self._cf_sub.setText(detail)
                self._cf_status_row.setStyleSheet(
                    f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:10px;}}")
                self._cf_status.setText(
                    'Infra ready — not ACTIVE until DNS + HTTPS health pass. Use Test / Repair.')
                self._cf_setup_btn.setText('Retry / Repair')
            elif state == 'running':
                self._cf_icon.setText('✓')
                self._cf_icon.setStyleSheet(f"font-size:22px; color:{C['warn']}; background:transparent;")
                self._cf_title.setText('Tunnel running — verifying…')
                self._cf_title.setStyleSheet(
                    f"color:{C['warn']}; font-size:14px; font-weight:700; background:transparent;")
                self._cf_sub.setText(detail)
                self._cf_status_row.setStyleSheet(
                    f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:10px;}}")
                self._cf_status.setText('Tunnel is up. HTTPS verify still needed for ACTIVE.')
                self._cf_setup_btn.setText('Retry / Repair')
            elif state == 'configured':
                self._cf_icon.setText('✓')
                self._cf_icon.setStyleSheet(f"font-size:22px; color:{C['warn']}; background:transparent;")
                self._cf_title.setText('Remote dashboard configured')
                self._cf_title.setStyleSheet(
                    f"color:{C['warn']}; font-size:14px; font-weight:700; background:transparent;")
                self._cf_sub.setText(detail)
                self._cf_status_row.setStyleSheet(
                    f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:10px;}}")
                self._cf_status.setText('Configured — awaiting ACTIVE (DNS + HTTPS).')
                self._cf_setup_btn.setText('Retry / Repair')
            elif state == 'vendor_token_missing':
                self._cf_icon.setText('!')
                self._cf_icon.setStyleSheet(f"font-size:22px; color:{C['err']}; background:transparent;")
                self._cf_title.setText('Vendor token required')
                self._cf_title.setStyleSheet(
                    f"color:{C['err']}; font-size:14px; font-weight:700; background:transparent;")
                self._cf_sub.setText(detail)
                self._cf_status_row.setStyleSheet(
                    f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:10px;}}")
                self._cf_status.setText(
                    'Contact MugoByte — place management API token in deploy.local.json. '
                    'Cashiers do not need Cloudflare login.')
                self._cf_setup_btn.setText('Retry auto-setup')
            elif state == 'broken':
                self._cf_icon.setText('!')
                self._cf_icon.setStyleSheet(f"font-size:22px; color:{C['err']}; background:transparent;")
                self._cf_title.setText('Remote setup needs vendor fix')
                self._cf_title.setStyleSheet(
                    f"color:{C['err']}; font-size:14px; font-weight:700; background:transparent;")
                self._cf_sub.setText(detail)
                self._cf_status_row.setStyleSheet(
                    f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:10px;}}")
                self._cf_status.setText(
                    'Vendor: fix central API token, or use Vendor recovery (browser) as last resort.')
                self._cf_setup_btn.setText('Retry auto-setup')
            elif remote and domain:
                self._cf_icon.setText('◐')
                self._cf_icon.setStyleSheet(f"font-size:22px; color:{C['warn']}; background:transparent;")
                self._cf_title.setText('Remote provisioning…')
                self._cf_title.setStyleSheet(
                    f"color:{C['warn']}; font-size:14px; font-weight:700; background:transparent;")
                self._cf_sub.setText(detail)
                self._cf_status_row.setStyleSheet(
                    f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:10px;}}")
                self._cf_status.setText(
                    'Automatic — tunnel is created on launch. No Cloudflare browser login needed.')
                self._cf_setup_btn.setText('Run setup now')
            else:
                self._cf_icon.setText('○')
                self._cf_icon.setStyleSheet(f"font-size:22px; color:{C['muted']}; background:transparent;")
                self._cf_title.setText('Remote dashboard not configured')
                self._cf_title.setStyleSheet(
                    f"color:{C['text']}; font-size:14px; font-weight:700; background:transparent;")
                self._cf_sub.setText(
                    'View sales and inventory from anywhere via your mugobyte.com link.')
                self._cf_status_row.setStyleSheet(
                    f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:10px;}}")
                self._cf_status.setText(
                    'Enable remote access — setup is automatic when the vendor API token is present.')
                self._cf_setup_btn.setText('Set Up Cloudflare')
        is_admin = self.user.get('user', {}).get('role', '') in ('admin', 'superadmin')
        for btn in (self._cf_setup_btn, self._cf_relogin_btn):
            btn.setEnabled(is_admin)
            btn.setVisible(is_admin)
        # Vendor recovery is emergency-only — keep visible for admin but not primary
        self._cf_test_btn.setEnabled(True)
        if hasattr(self, '_cf_repair_btn'):
            self._cf_repair_btn.setEnabled(is_admin)
            self._cf_repair_btn.setVisible(is_admin)

    def _toggle_cf_remote_box(self):
        remote = self._cf_mode_remote.isChecked()
        self._cf_remote_box.setEnabled(remote)
        if remote:
            self._update_cf_preview()

    def _production_subdomain(self) -> str:
        """DNS slug always derived from shop name — one shop, one URL."""
        try:
            from backend.cloudflare_setup import shop_to_subdomain, load_web_config
            shop = self.shop_name.text().strip()
            if shop:
                return shop_to_subdomain(shop)
            wcfg = load_web_config()
            return (wcfg.get('tunnel_subdomain') or '').strip()
        except Exception:
            return ''

    def _update_cf_preview(self):
        sub = self._production_subdomain()
        self._cf_subdomain.setText(sub or '—')
        try:
            from backend.cloudflare_setup import full_domain
            if sub:
                dom = full_domain(sub)
                self._cf_preview.setText(f'https://{dom}')
            else:
                self._cf_preview.setText('https://….mugobyte.com')
        except Exception:
            self._cf_preview.setText('https://….mugobyte.com')

    def _cf_log_append(self, level, msg):
        colours = {'ok': C['ok'], 'error': C['err'], 'warn': C['warn']}
        colour = colours.get(level, C['text2'])
        self._cf_log.append(f'<span style="color:{colour}">{msg}</span>')
        self._cf_log.verticalScrollBar().setValue(
            self._cf_log.verticalScrollBar().maximum())

    def _save_web_remote_config(self, remote_setup_ok=None):
        try:
            from backend.cloudflare_setup import (
                full_domain, save_web_config, shop_to_subdomain,
            )
            remote = self._cf_mode_remote.isChecked()
            sub = self._production_subdomain()
            if remote and sub:
                slug = shop_to_subdomain(sub)
                payload = {
                    'base_domain': 'mugobyte.com',
                    'tunnel_subdomain': slug,
                    'tunnel_domain': full_domain(sub),
                    'tunnel_name': f'mbt-pos-{slug}',
                    'remote_enabled': True,
                }
                if remote_setup_ok is not None:
                    payload['remote_setup_ok'] = remote_setup_ok
                save_web_config(payload)
            else:
                save_web_config({'remote_enabled': False})
        except Exception:
            pass

    def _cf_setup_or_fix(self):
        """Primary action: start existing tunnel or API auto-setup (no browser)."""
        force = False
        try:
            from backend.cloudflare_setup import get_remote_dashboard_status
            st = get_remote_dashboard_status().get('state')
            # Never force browser from primary button — Vendor recovery only
            force = False
            if st == 'vendor_token_missing':
                QMessageBox.warning(
                    self, 'Vendor token required',
                    'Central Cloudflare management API token is missing or wrong type.\n\n'
                    'MugoByte must place a cfat_… token in:\n'
                    '  config/deploy.local.json (before BUILD), or\n'
                    '  %LOCALAPPDATA%\\MugoByte\\MBT POS\\config\\deploy.local.json\n\n'
                    'Shop staff do not log into Cloudflare.\n'
                    'Use “Vendor recovery” only as last-resort emergency.')
                return
        except Exception:
            force = False
        self._run_cloudflare_setup(force)

    def _require_cf_admin(self):
        if self.user.get('user', {}).get('role', '') not in ('admin', 'superadmin'):
            QMessageBox.warning(self, 'Permission', 'Admin only.')
            return False
        return True

    def _run_cloudflare_setup(self, force_relogin=False):
        if self._cf_setup_running:
            return
        if force_relogin:
            reply = QMessageBox.question(
                self, 'Vendor recovery — Cloudflare browser login',
                'Emergency only. This opens a browser login for the MugoByte '
                'Cloudflare account that owns mugobyte.com.\n\n'
                'Normal shop installs must NOT need this — use the central '
                'management API token in deploy.local.json instead.\n\nContinue?',
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        if not self._require_cf_admin():
            return
        if not self._cf_mode_remote.isChecked():
            QMessageBox.warning(self, 'Remote Access',
                'Select “Remote access” first.')
            return
        shop = self.shop_name.text().strip()
        if not shop:
            QMessageBox.warning(self, 'Required', 'Enter shop name first.')
            return
        sub = self._production_subdomain()
        if not sub:
            QMessageBox.warning(self, 'Required', 'Shop name could not be converted to a URL.')
            return
        wcfg = {}
        try:
            from backend.cloudflare_setup import load_web_config
            wcfg = load_web_config()
        except Exception:
            pass
        live_sub = (wcfg.get('tunnel_subdomain') or '').strip()
        if live_sub and live_sub != sub and wcfg.get('remote_setup_ok'):
            reply = QMessageBox.warning(
                self, 'Change Remote URL?',
                f'This shop is already live at:\n'
                f'  https://{live_sub}.mugobyte.com\n\n'
                f'Shop name would create:\n'
                f'  https://{sub}.mugobyte.com\n\n'
                f'In production, keep the original URL unless MugoByte approves a change.\n'
                f'Continue and run full setup?',
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        # Already configured with credentials → start only (no re-auth)
        if not force_relogin:
            try:
                from backend.cloudflare_setup import (
                    _remote_infra_ready, CloudflareTunnelService,
                    refresh_remote_setup_status,
                )
                if _remote_infra_ready():
                    self._cf_status.setText('Already configured — starting tunnel…')
                    ok = CloudflareTunnelService().start()
                    refresh_remote_setup_status()
                    self._refresh_cf_status()
                    if ok:
                        QMessageBox.information(
                            self, 'Remote Dashboard',
                            'Tunnel was already configured and is now running.\n'
                            'No re-login needed.')
                        return
            except Exception:
                pass
        self._cf_setup_running = True
        self._save_web_remote_config(remote_setup_ok=False)
        self._cf_setup_btn.setEnabled(False)
        self._cf_test_btn.setEnabled(False)
        self._cf_relogin_btn.setEnabled(False)
        self._cf_status.setText('⏳ Setting up Cloudflare tunnel…')
        self._cf_log.clear()

        def _cb(level, msg):
            QTimer.singleShot(0, lambda l=level, m=msg: self._cf_log_append(l, m))

        def worker():
            try:
                from backend.cloudflare_setup import CloudflareSetup
                result = CloudflareSetup(
                    shop, subdomain=sub, log_callback=_cb,
                    force_relogin=force_relogin,
                ).run()
                QTimer.singleShot(0, lambda: self._on_cf_setup_done(result))
            except Exception as e:
                QTimer.singleShot(0, lambda: self._on_cf_setup_done({
                    'ok': False, 'errors': [str(e)], 'log_path': '',
                }))

        threading.Thread(target=worker, daemon=True).start()

    def _on_cf_setup_done(self, result: dict):
        self._cf_setup_running = False
        self._cf_setup_btn.setEnabled(True)
        self._cf_test_btn.setEnabled(True)
        self._cf_relogin_btn.setEnabled(True)
        if result.get('ok'):
            # ACTIVE only when setup verified HTTPS — never force remote_setup_ok
            active = bool(result.get('active') or result.get('remote_ok'))
            self._save_web_remote_config(remote_setup_ok=True if active else False)
            try:
                from backend.cloudflare_setup import refresh_remote_setup_status
                refresh_remote_setup_status()
            except Exception:
                pass
            if active:
                self._cf_status.setText(
                    '✓ Cloudflare ACTIVE — remote URL is live. '
                    'Tunnel auto-starts every launch.')
            else:
                self._cf_status.setText(
                    '✓ Tunnel configured — DNS/HTTPS still propagating. '
                    'Not ACTIVE yet; use Test Connection / Retry in a few minutes.')
            self._cf_status.setStyleSheet(
                f"color:{C['ok' if active else 'warn']}; font-size:13px; font-weight:600;")
        else:
            errs = '; '.join(result.get('errors', [])[:2]) or 'Setup failed'
            self._cf_status.setText(f'✗ {errs}')
            self._cf_status.setStyleSheet(
                f"color:{C['err']}; font-size:13px; font-weight:600;")
            log_path = result.get('log_path', '')
            if log_path:
                self._cf_log.append(
                    f'<span style="color:{C["muted"]}">Full log: {log_path}</span>')
        self._refresh_cf_status()

    def _test_cloudflare(self):
        self._cf_status.setText('⏳ Running diagnostics…')
        self._cf_test_btn.setEnabled(False)

        def _cb(level, msg):
            QTimer.singleShot(0, lambda l=level, m=msg: self._cf_log_append(l, m))

        def worker():
            try:
                from backend.cloudflare_setup import run_diagnostics
                rep = run_diagnostics(_cb)
                QTimer.singleShot(0, lambda: self._on_cf_test_done(rep))
            except Exception as e:
                QTimer.singleShot(0, lambda: self._on_cf_test_done(
                    {'ok': False, 'checks': [], 'error': str(e)}))

        threading.Thread(target=worker, daemon=True).start()

    def _on_cf_test_done(self, report: dict):
        self._cf_test_btn.setEnabled(True)
        ok = report.get('ok', False)
        self._cf_status.setText(
            '✓ All checks passed.' if ok else '✗ Some checks failed — see log below.')
        self._cf_status.setStyleSheet(
            f"color:{C['ok' if ok else 'err']}; font-size:13px; font-weight:600;")
        for c in report.get('checks', []):
            mark = 'OK' if c.get('ok') else 'FAIL'
            fix = f" — Fix: {c['fix']}" if not c.get('ok') and c.get('fix') else ''
            self._cf_log_append(
                'ok' if c.get('ok') else 'error',
                f'{mark}: {c.get("name")} ({c.get("detail", "")}){fix}')
        self._refresh_cf_status()

    def _refresh_tg_status(self):
        chat_id = self.tg_chat.text().strip()
        if chat_id:
            self._tg_icon.setText('✓')
            self._tg_icon.setStyleSheet(f"font-size:22px; color:{C['ok']}; background:transparent;")
            self._tg_title.setText('Telegram connected')
            self._tg_title.setStyleSheet(
                f"color:{C['ok']}; font-size:14px; font-weight:700; background:transparent;")
            self._tg_sub.setText(
                f'Chat ID: {chat_id}  ·  Reports and keys will be sent to your Telegram.')
            self._tg_status_row.setStyleSheet(
                f"QFrame{{background:{C['ok_dim']};border:1px solid {qss_alpha(C['ok'], 0.25)};"
                f"border-radius:10px;}}")
            self._connect_btn.hide()
            self._test_tg_btn.show()
            self._disconnect_btn.show()
        else:
            self._tg_icon.setText('○')
            self._tg_icon.setStyleSheet(f"font-size:22px; color:{C['muted']}; background:transparent;")
            self._tg_title.setText('Telegram not connected')
            self._tg_title.setStyleSheet(
                f"color:{C['text']}; font-size:14px; font-weight:700; background:transparent;")
            self._tg_sub.setText('Connect to receive reports and license keys via Telegram.')
            self._tg_status_row.setStyleSheet(
                f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};"
                f"border-radius:10px;}}")
            self._connect_btn.show()
            self._test_tg_btn.hide()
            self._disconnect_btn.hide()

    # ── Telegram connect flow ─────────────────────────────────────────────────

    def _start_connect(self):
        if self._polling:
            return
        from backend.telegram_hub import resolve_bot_token, wait_for_chat_message

        cfg = self.api.get_settings() or {}
        token = resolve_bot_token(cfg) or self.tg_token.text().strip()
        if token and not self.tg_token.text().strip():
            self.tg_token.setText(token)
        if not token:
            QMessageBox.warning(
                self, 'Telegram Not Ready',
                'Telegram could not start.\n\n'
                'Close MBT POS completely, open it again, then click Connect.\n'
                'If this continues, reinstall from the latest MBT_POS_Setup.exe.')
            return

        import requests
        try:
            r = requests.get(f'https://api.telegram.org/bot{token}/getMe', timeout=12)
            if not r.ok:
                QMessageBox.warning(
                    self, 'Telegram Error',
                    'Could not reach the MugoByte Telegram bot.\n\n'
                    'Check your internet connection and try again.')
                return
        except Exception:
            QMessageBox.warning(
                self, 'Telegram Blocked',
                'This PC cannot reach Telegram (api.telegram.org).\n\n'
                'Your internet may work, but Telegram is blocked on this network.\n'
                'Turn on VPN on this computer, then try Connect again.')
            return

        bot = getattr(self, '_bot_username', 'mbt_admin1_bot')
        self._polling = True
        self._connect_btn.setEnabled(False)
        self._connect_btn.setText('Waiting…')
        self._tg_progress.setText(
            f'⏳  Open Telegram, message @{bot}, then wait here…')
        self._tg_progress.setStyleSheet(
            f"color:{C['warn']}; font-size:12px; background:transparent;")
        self._tg_progress.show()

        welcome = (
            "✅ <b>MBT POS connected!</b>\n"
            "Hello {name} — your Telegram is now linked.\n"
            "You'll receive sales reports and license keys here.\n"
            "<i>MugoByte Technologies</i>"
        )

        def on_chat(chat_id, _msg):
            self._chat_found.emit(chat_id)

        def on_err(msg):
            self._chat_error.emit(msg)

        def on_to():
            self._chat_timeout.emit()

        threading.Thread(
            target=wait_for_chat_message,
            args=(self.config_getter, on_chat, on_to, on_err, 180, welcome),
            daemon=True,
        ).start()

    def _on_chat_found(self, chat_id: str):
        self._polling = False
        self.tg_chat.setText(chat_id)
        self._tg_progress.hide()
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText('📲  Connect My Telegram')
        # Auto-save the chat ID immediately
        self._save_silent()
        self._refresh_tg_status()
        self._tg_progress.setText('✓ Telegram connected successfully.')
        self._tg_progress.setStyleSheet(
            f"color:{C['ok']}; font-size:12px; background:transparent;")
        self._tg_progress.show()

    def _on_chat_timeout(self):
        self._polling = False
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText('📲  Connect My Telegram')
        self._tg_progress.setText(
            '⏰  Timed out — send a message to @mbt_admin1_bot and try again.')
        self._tg_progress.setStyleSheet(
            f"color:{C['err']}; font-size:12px; background:transparent;")

    def _on_chat_error(self, msg: str):
        self._polling = False
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText('📲  Connect My Telegram')
        self._tg_progress.setText(f'Error: {msg}')
        self._tg_progress.setStyleSheet(
            f"color:{C['err']}; font-size:12px; background:transparent;")
        self._tg_progress.show()

    def _disconnect(self):
        reply = QMessageBox.question(self, 'Disconnect Telegram',
            'Remove your Telegram connection?\n'
            'You will no longer receive reports or keys via Telegram.',
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.tg_chat.setText('')
            self._save_silent()
            self._refresh_tg_status()

    # ── Save ──────────────────────────────────────────────────────────────────

    def _common_payload(self):
        return {
            'shop_name':           self.shop_name.text().strip(),
            'shop_address':        self.shop_address.text().strip(),
            'shop_phone':          self.shop_phone.text().strip(),
            'currency_symbol':     self.currency.currentText(),
            'tax_rate':            str(self.tax_rate.value()),
            'receipt_footer':      self.receipt_footer.text().strip(),
            'auto_print':          '1' if self.auto_print.isChecked() else '0',
            'printer_port':        self.printer_port.text().strip(),
            'telegram_bot_token':  self.tg_token.text().strip(),
            'telegram_chat_id':    self.tg_chat.text().strip(),
            'developer_chat_id':   self.dev_chat.text().strip(),
            'sync_interval':       str(self.sync_interval.value()),
            'mpesa_mode':          'stk' if self.mpesa_mode.currentIndex() == 1 else 'manual',
            'mpesa_till':          self.mpesa_till.text().strip(),
            'mpesa_paybill':       self.mpesa_paybill.text().strip(),
            'mpesa_business_name': self.mpesa_business.text().strip(),
            'auto_report_daily':   '1' if self.auto_report_daily.isChecked() else '0',
            'auto_report_weekly':  '1' if self.auto_report_weekly.isChecked() else '0',
            'auto_db_backup':      '1' if self.auto_db_backup.isChecked() else '0',
            'auto_db_backup_interval_hours': '24',
            'auto_report_interval_hours': '4',
            'variance_enabled': '1' if self.variance_enabled.isChecked() else '0',
            'variance_enable_deposits': '1' if self.variance_enable_deposits.isChecked() else '0',
            'variance_enable_tips': '1' if self.variance_enable_tips.isChecked() else '0',
            'variance_enable_transport': '1' if self.variance_enable_transport.isChecked() else '0',
            'variance_require_customer_deposit':
                '1' if self.variance_require_customer.isChecked() else '0',
            'variance_allow_refund_after_finalize':
                '1' if self.variance_allow_refund.isChecked() else '0',
            'variance_max_cashier': str(self.variance_max_cashier.value()),
            'cash_rounding_enabled':
                '1' if self.cash_rounding_enabled.isChecked() else '0',
            'cash_rounding_apply_cash':
                '1' if self.cash_rounding_apply_cash.isChecked() else '0',
            'cash_rounding_apply_mpesa':
                '1' if self.cash_rounding_apply_mpesa.isChecked() else '0',
            'cash_rounding_apply_card':
                '1' if self.cash_rounding_apply_card.isChecked() else '0',
            'cash_rounding_apply_bank':
                '1' if self.cash_rounding_apply_bank.isChecked() else '0',
            'cash_rounding_mode':
                self.cash_rounding_mode.currentData() or 'nearest',
            'cash_rounding_value': str(int(self.cash_rounding_value.value())),
            'after_sale_default_customer':
                self.after_sale_default_customer.currentData() or 'walk_in',
            'after_sale_default_payment':
                self.after_sale_default_payment.currentText() or 'Cash',
            'after_sale_focus_barcode':
                '1' if self.after_sale_focus_barcode.isChecked() else '0',
            'after_sale_auto_clear_cart':
                '1' if self.after_sale_auto_clear_cart.isChecked() else '0',
            'after_sale_reset_discounts':
                '1' if self.after_sale_reset_discounts.isChecked() else '0',
            'after_sale_reset_notes':
                '1' if self.after_sale_reset_notes.isChecked() else '0',
            'autofill_cash_paid':
                '1' if self.autofill_cash_paid.isChecked() else '0',
            'autofill_product_defaults':
                '1' if self.autofill_product_defaults.isChecked() else '0',
            'autofill_reports_today':
                '1' if self.autofill_reports_today.isChecked() else '0',
            'autofill_clear_search_on_leave':
                '1' if self.autofill_clear_search_on_leave.isChecked() else '0',
            'autofill_credit_customer_info':
                '1' if self.autofill_credit_customer_info.isChecked() else '0',
        }

    def _save(self):
        if not self.shop_name.text().strip():
            QMessageBox.warning(self, 'Required', 'Shop name is required.'); return
        res = self.api.update_settings(self._common_payload())
        if res and res.get('success'):
            self._save_web_remote_config()
            self._save_category_visual_prefs()
            self._save_audio_settings()
            self._refresh_cf_status()
            try:
                from desktop.utils.audio_manager import play as _audio_play
                _audio_play('save')
            except Exception:
                pass
            QMessageBox.information(self, 'Saved', 'Settings saved.')
        else:
            try:
                from desktop.utils.audio_manager import play as _audio_play
                _audio_play('error')
            except Exception:
                pass
            QMessageBox.critical(self, 'Error', 'Failed to save settings.')

    def _save_audio_settings(self):
        panel = getattr(self, '_audio_panel', None)
        if panel is None:
            return
        try:
            panel.save_silent()
        except Exception:
            try:
                from desktop.utils.audio_manager import get_audio
                get_audio().save_settings(panel.collect_patch())
            except Exception:
                pass

    def _save_category_visual_prefs(self):
        try:
            from desktop.utils.category_visuals import save_visual_prefs
            save_visual_prefs({
                'tile_size': int(self.cv_tile_size.value()),
                'corner_radius': int(self.cv_corner.value()),
                'image_fit': self.cv_fit.currentData() or 'cover',
                'show_labels': self.cv_show_labels.isChecked(),
                'show_accent': self.cv_show_accent.isChecked(),
                'compact_mode': self.cv_compact.isChecked(),
                'default_placeholder': (self.cv_placeholder.text() or '').strip()
                    or 'generic/_placeholder.svg',
            })
        except Exception:
            pass

    def _open_category_manager(self):
        from desktop.dialogs.category_manager import CategoryManagerDialog
        CategoryManagerDialog(self.api, self).exec_()

    def _save_silent(self):
        """Save without any dialog — used for auto-saves like chat ID linking."""
        try:
            self.api.update_settings(self._common_payload())
            self._save_category_visual_prefs()
        except Exception:
            pass

    # ── Actions ───────────────────────────────────────────────────────────────

    def _test_print(self):
        try:
            sys.path.insert(0, _PR)
            from printing.printer_engine import PrinterManager
            PrinterManager(lambda: self.api.get_settings() or {}).test_print()
            QMessageBox.information(self, 'Test', 'Test page queued.')
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))

    def _send_report_now(self):
        chat = self.tg_chat.text().strip()
        if not chat:
            QMessageBox.warning(self, 'Telegram Required',
                'Connect Telegram first to receive reports.'); return
        self._send_report_now_btn.setEnabled(False)
        self._send_report_now_btn.setText('Sending…')
        from backend.telegram_reporter import send_report_now

        def on_done(ok, msg):
            def _ui():
                self._send_report_now_btn.setEnabled(True)
                self._send_report_now_btn.setText('Send Today\'s Report Now')
                if ok:
                    QMessageBox.information(self, 'Report Sent', msg)
                else:
                    QMessageBox.warning(self, 'Report', msg)
            QTimer.singleShot(0, _ui)

        send_report_now(self.api, self.config_getter, on_done=on_done)

    def _send_backup_now(self):
        chat = self.tg_chat.text().strip()
        if not chat:
            QMessageBox.warning(self, 'Telegram Required',
                'Connect Telegram first to receive database backups.')
            return
        self._send_backup_now_btn.setEnabled(False)
        self._send_backup_now_btn.setText('Backing up…')
        from backend.db_backup import send_db_backup_now

        def on_done(ok, msg):
            def _ui():
                self._send_backup_now_btn.setEnabled(True)
                self._send_backup_now_btn.setText('Send Database Backup Now')
                if ok:
                    QMessageBox.information(self, 'Backup Sent', msg)
                else:
                    QMessageBox.warning(self, 'Backup', msg)
            QTimer.singleShot(0, _ui)

        send_db_backup_now(self.config_getter, api=self.api, on_done=on_done, reason='manual')

    def _test_tg(self):
        try:
            sys.path.insert(0, _PR)
            from backend.internet_monitor import send_telegram_message
            token   = self.tg_token.text().strip()
            chat    = self.tg_chat.text().strip()
            if not token or not chat:
                QMessageBox.warning(self, 'Not Connected',
                    'Connect your Telegram first.'); return
            shop = self.shop_name.text().strip() or 'MBT POS'
            ok = send_telegram_message(
                token, chat,
                f"✅ <b>Test — {shop}</b>\nTelegram is working correctly.\n"
                f"<i>MugoByte Technologies</i>")
            if ok:
                QMessageBox.information(self, 'Sent ✓', 'Test message sent to your Telegram!')
            else:
                QMessageBox.critical(self, 'Failed',
                    'Could not send. Check your internet connection.')
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))

    def _void_sale(self):
        from desktop.utils.security import prompt_void_sale
        receipt = self._void_receipt.text().strip()
        if prompt_void_sale(self.api, self, receipt_prefill=receipt):
            self._void_receipt.clear()

    def _reset_wiz(self):
        if self.user.get('user', {}).get('role', '') not in ('admin', 'superadmin'):
            QMessageBox.warning(self, 'Permission', 'Admin only.'); return
        pw, ok = QInputDialog.getText(
            self, 'Confirm', 'Admin password:', QLineEdit.Password)
        if not ok or not pw: return
        try:
            res = self.api.login(self.user.get('user', {}).get('username', 'admin'), pw)
            if not res or 'token' not in res:
                QMessageBox.warning(self, 'Wrong', 'Incorrect password.'); return
        except Exception:
            QMessageBox.critical(self, 'Error', 'Could not verify.'); return
        try:
            sys.path.insert(0, _PR)
            from desktop.wizard.setup_wizard import reset_wizard
            reset_wizard()
            QMessageBox.information(self, 'Done', 'Wizard reset. Restart to re-run setup.')
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))


class SecuritySettingsTab(QWidget):
    """Super-admin PIN management — embedded in Settings."""
    def __init__(self, api, user, config_getter):
        super().__init__()
        self.api = api; self.user = user; self.config_getter = config_getter
        self._build()

    def _build(self):
        from desktop.utils.widgets import page_layout, section_card
        lay, _ = page_layout(self, margins=(0, 0, 0, 0), spacing=12)
        from PyQt5.QtWidgets import QFormLayout
        grp, body = section_card('🔐', 'Super-Admin PIN', 'Required for stock adjust, voids, and overrides')
        fl  = QFormLayout(); fl_w = QWidget(); fl_w.setLayout(fl)

        info = QLabel(
            'The Super-Admin PIN is required to:\n'
            '  • Adjust stock quantities directly\n'
            '  • Void / edit completed sales\n'
            '  • Access security overrides\n'
            '  • Clear audit logs\n\n'
            'Keep this PIN strictly private — do NOT share with cashiers.')
        info.setStyleSheet(f"color:{C['text2']}; font-size:13px; background:transparent;")
        info.setWordWrap(True)
        fl.addRow(info)

        self._current = QLineEdit(); self._current.setEchoMode(QLineEdit.Password)
        self._current.setMinimumHeight(40); self._current.setPlaceholderText('Current PIN (leave blank if not set)')
        self._new     = QLineEdit(); self._new.setEchoMode(QLineEdit.Password)
        self._new.setMinimumHeight(40); self._new.setPlaceholderText('New PIN (min 6 digits)')
        self._confirm = QLineEdit(); self._confirm.setEchoMode(QLineEdit.Password)
        self._confirm.setMinimumHeight(40); self._confirm.setPlaceholderText('Confirm new PIN')

        for lbl, w in [('Current PIN', self._current),
                        ('New PIN', self._new),
                        ('Confirm PIN', self._confirm)]:
            l = QLabel(lbl); l.setStyleSheet(f"color:{C['text2']}; font-size:13px;")
            fl.addRow(l, w)

        save = PrimaryBtn('Set Super-Admin PIN', 44)
        save.clicked.connect(self._save_pin); fl.addRow(save)
        body.addWidget(fl_w)
        lay.addWidget(grp)

    def _save_pin(self):
        from desktop.utils.security import verify_superadmin_pin, set_superadmin_pin
        new = self._new.text().strip()
        conf = self._confirm.text().strip()
        if len(new) < 6:
            QMessageBox.warning(self,'Too Short','PIN must be at least 6 characters.'); return
        if new != conf:
            QMessageBox.warning(self,'Mismatch','New PIN and confirmation do not match.'); return
        cfg = self.api.get_settings() or {}
        if cfg.get('superadmin_pin_hash'):
            curr = self._current.text().strip()
            if not curr:
                QMessageBox.warning(self,'Required','Enter current PIN to change it.'); return
            if not verify_superadmin_pin(curr, self.api, self, log_attempt=True):
                return
        if set_superadmin_pin(new, self.api):
            QMessageBox.information(self,'✓ Saved','Super-Admin PIN updated.')
            self._current.clear(); self._new.clear(); self._confirm.clear()
        else:
            QMessageBox.critical(self,'Error','Failed to save PIN.')
