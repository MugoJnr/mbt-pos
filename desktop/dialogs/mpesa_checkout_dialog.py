"""
M-Pesa checkout dialog — capability-aware STK + Till wait + manual reference.

Checkout UI is independent of Daraja. PaymentService owns verification.
Sale is NOT created here — caller creates sale once after VERIFIED.
"""
from __future__ import annotations

import json
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QMessageBox, QFrame, QComboBox,
)

from desktop.payments.models import PaymentChannel, PaymentRecord, PaymentStatus
from desktop.payments.security import mask_phone, normalize_ke_phone


class MpesaCheckoutDialog(QDialog):
    """Returns Accepted only when payment.status == verified (or overpaid accepted)."""

    def __init__(
        self,
        parent,
        *,
        payment_service,
        amount: float,
        cart: list,
        currency: str = 'KES',
        cashier_id=None,
        cashier_name: str = '',
        customer_name: str = '',
        initial_phone: str = '',
        account_reference: str = '',
        initial_ref: str = '',
        allow_underpay_as_part: bool = True,
    ):
        super().__init__(parent)
        self.setWindowTitle('M-Pesa Payment')
        self.setModal(True)
        self.resize(440, 560)
        self.svc = payment_service
        self.amount = round(float(amount), 2)
        self.cart = cart
        self.currency = currency
        self.cashier_id = cashier_id
        self.cashier_name = cashier_name
        self.customer_name = customer_name
        self.account_reference = account_reference
        self.allow_underpay_as_part = bool(allow_underpay_as_part)
        self.payment: Optional[PaymentRecord] = None
        self.caps = self.svc.get_capabilities()
        self._poll = QTimer(self)
        self._poll.setInterval(2500)
        self._poll.timeout.connect(self._on_poll)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        title = QLabel(f'Collect {currency} {self.amount:,.2f} via M-Pesa')
        title.setStyleSheet('font-size:16px; font-weight:600;')
        root.addWidget(title)

        biz = self.caps.business_name or 'Shop'
        till_bits = []
        if self.caps.till_number:
            till_bits.append(f'Till {self.caps.till_number}')
        if self.caps.paybill_number:
            till_bits.append(f'Paybill {self.caps.paybill_number}')
        info = QLabel(f'{biz}' + (f' · {" · ".join(till_bits)}' if till_bits else ''))
        info.setWordWrap(True)
        root.addWidget(info)

        env = QLabel(f'Environment: {self.caps.environment}')
        env.setStyleSheet('color:#666; font-size:11px;')
        root.addWidget(env)

        self.phone = QLineEdit()
        self.phone.setPlaceholderText('Customer phone (07… / 2547…)')
        self.phone.setText(initial_phone or '')
        root.addWidget(QLabel('Phone'))
        root.addWidget(self.phone)

        self.status = QLabel('Create payment to begin. Request accepted ≠ paid.')
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            'background:#f5f5f5; padding:10px; border-radius:6px;'
        )
        root.addWidget(self.status)

        self.candidates = QTextEdit()
        self.candidates.setReadOnly(True)
        self.candidates.setMaximumHeight(100)
        self.candidates.hide()
        root.addWidget(self.candidates)

        self.ref_edit = QLineEdit()
        self.ref_edit.setPlaceholderText('M-Pesa receipt / reference (manual)')
        if initial_ref:
            self.ref_edit.setText(initial_ref)
        root.addWidget(QLabel('Manual reference (offline fallback)'))
        root.addWidget(self.ref_edit)

        row = QHBoxLayout()
        self.btn_stk = QPushButton('Send Prompt')
        self.btn_stk.clicked.connect(self._send_stk)
        self.btn_stk.setVisible(bool(self.caps.can_send_prompt))
        row.addWidget(self.btn_stk)

        self.btn_wait = QPushButton('Wait for Till / Paybill')
        self.btn_wait.clicked.connect(self._wait_till)
        self.btn_wait.setVisible(bool(self.caps.can_detect_till or self.caps.till_number or self.caps.paybill_number))
        row.addWidget(self.btn_wait)

        self.btn_manual = QPushButton('Confirm Manual Ref')
        self.btn_manual.clicked.connect(self._manual)
        row.addWidget(self.btn_manual)
        root.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_query = QPushButton('Query Status')
        self.btn_query.clicked.connect(self._query)
        self.btn_query.setEnabled(False)
        row2.addWidget(self.btn_query)

        self.btn_confirm = QPushButton('Confirm Selected Match')
        self.btn_confirm.clicked.connect(self._confirm_match)
        self.btn_confirm.setEnabled(False)
        row2.addWidget(self.btn_confirm)
        root.addLayout(row2)

        self.match_pick = QComboBox()
        self.match_pick.hide()
        root.addWidget(self.match_pick)

        foot = QHBoxLayout()
        self.btn_cancel = QPushButton('Cancel')
        self.btn_cancel.clicked.connect(self.reject)
        foot.addWidget(self.btn_cancel)
        self.btn_underpay = QPushButton('Accept as Part Pay')
        self.btn_underpay.setEnabled(False)
        self.btn_underpay.setVisible(False)
        self.btn_underpay.clicked.connect(self._accept_underpay)
        foot.addWidget(self.btn_underpay)
        self.btn_done = QPushButton('Complete Sale')
        self.btn_done.setEnabled(False)
        self.btn_done.clicked.connect(self._finish)
        foot.addWidget(self.btn_done)
        root.addLayout(foot)

        # Create pending payment immediately (idempotent key unique per dialog open)
        try:
            self.payment = self.svc.create_pending_payment(
                amount=self.amount,
                cart=self.cart,
                channel=PaymentChannel.TILL.value if not self.caps.can_send_prompt else PaymentChannel.STK.value,
                phone=self.phone.text().strip(),
                customer_name=self.customer_name,
                cashier_id=self.cashier_id,
                cashier_name=self.cashier_name,
                account_reference=self.account_reference,
            )
            self._set_status(
                f'Payment {self.payment.id[-8:]} pending — '
                f'not paid until verified.'
            )
            self.btn_query.setEnabled(True)
        except Exception as e:
            self._set_status(f'Failed to create payment: {e}')
            self.btn_stk.setEnabled(False)
            self.btn_wait.setEnabled(False)
            self.btn_manual.setEnabled(False)

    def _set_status(self, text: str):
        self.status.setText(text)

    def _refresh_from_payment(self):
        if not self.payment:
            return
        p = self.svc.get_payment(self.payment.id) or self.payment
        self.payment = p
        st = p.status
        msg = (
            f'Status: {st}\n'
            f'Expected: {self.currency} {p.amount_expected:,.2f}\n'
            f'Received: {self.currency} {float(p.amount_received or 0):,.2f}\n'
            f'Ref: {p.provider_reference or "—"}\n'
            f'Phone: {p.phone_masked or mask_phone(self.phone.text())}'
        )
        if p.error_message:
            msg += f'\n{p.error_message}'
        self._set_status(msg)

        if st in (PaymentStatus.VERIFIED.value,):
            self.btn_done.setEnabled(True)
            self.btn_underpay.setEnabled(False)
            self.btn_underpay.setVisible(False)
            self._poll.stop()
        elif st == PaymentStatus.OVERPAID.value:
            self.btn_done.setEnabled(True)
            self.btn_underpay.setVisible(False)
            self._set_status(msg + '\nOverpayment — confirm to accept before sale.')
        elif st == PaymentStatus.UNDERPAID.value:
            self.btn_done.setEnabled(False)
            if self.allow_underpay_as_part:
                self.btn_underpay.setVisible(True)
                self.btn_underpay.setEnabled(True)
                self._set_status(
                    msg + '\nUnderpaid — not silent. Use Accept as Part Pay or wait for full amount.'
                )
            else:
                self.btn_underpay.setVisible(False)
                self.btn_underpay.setEnabled(False)
                self._set_status(msg + '\nUnderpaid — wait for full amount (part accept disabled).')
        elif st == PaymentStatus.NEEDS_CONFIRMATION.value:
            self.btn_confirm.setEnabled(True)
            self.btn_underpay.setVisible(False)
            self._show_candidates(p)
        elif st in (
            PaymentStatus.FAILED.value,
            PaymentStatus.CANCELLED.value,
            PaymentStatus.EXPIRED.value,
        ):
            self._poll.stop()
            self.btn_done.setEnabled(False)
            self.btn_underpay.setEnabled(False)
            self.btn_underpay.setVisible(False)

    def _show_candidates(self, payment: PaymentRecord):
        try:
            cands = json.loads(payment.match_candidates_json or '[]')
        except Exception:
            cands = []
        self.candidates.show()
        self.match_pick.show()
        self.match_pick.clear()
        lines = ['Ambiguous matches — confirm manually (never auto-guess):']
        for c in cands:
            label = (
                f"{c.get('provider_reference')} · "
                f"{self.currency} {float(c.get('amount') or 0):,.2f} · "
                f"{c.get('phone_masked') or ''}"
            )
            lines.append(label)
            self.match_pick.addItem(label, c.get('provider_reference'))
        self.candidates.setPlainText('\n'.join(lines))

    def _ensure_payment(self) -> bool:
        return self.payment is not None

    def _send_stk(self):
        if not self._ensure_payment():
            return
        phone = self.phone.text().strip()
        if not normalize_ke_phone(phone):
            QMessageBox.warning(self, 'Phone', 'Enter a valid Kenyan mobile number.')
            return
        try:
            self.payment = self.svc.send_stk(self.payment.id, phone=phone)
            self._refresh_from_payment()
            self._poll.start()
            # Explicit: accepted ≠ paid
            if self.payment.status == PaymentStatus.AWAITING_CUSTOMER.value:
                self._set_status(
                    self.status.text()
                    + '\n\nSTK request accepted by network — waiting for customer. NOT paid yet.'
                )
        except Exception as e:
            QMessageBox.warning(self, 'STK', str(e))

    def _wait_till(self):
        if not self._ensure_payment():
            return
        try:
            self.payment = self.svc.sync_incoming_and_match(self.payment.id)
            self._refresh_from_payment()
            self._poll.start()
        except Exception as e:
            QMessageBox.warning(self, 'Till match', str(e))

    def _manual(self):
        if not self._ensure_payment():
            return
        ref = self.ref_edit.text().strip()
        if len(ref) < 6:
            QMessageBox.warning(self, 'Reference', 'Enter the full M-Pesa receipt number.')
            return
        try:
            # Offline/manual: force verify after cashier confirmation
            reply = QMessageBox.question(
                self, 'Confirm manual M-Pesa',
                f'Confirm reference {ref.upper()} for '
                f'{self.currency} {self.amount:,.2f}?\n\n'
                'This is audited. Do not enter M-Pesa PIN here.',
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self.payment = self.svc.register_manual_reference(
                self.payment.id,
                ref,
                amount=self.amount,
                confirmed_by=self.cashier_name or 'cashier',
                notes='manual_pos_fallback',
                force_verify=True,
            )
            self._refresh_from_payment()
        except Exception as e:
            QMessageBox.warning(self, 'Manual', str(e))

    def _query(self):
        if not self._ensure_payment():
            return
        try:
            # Query — never double-STK
            if self.payment.checkout_request_id:
                self.payment = self.svc.query_payment(self.payment.id)
            else:
                self.payment = self.svc.sync_incoming_and_match(self.payment.id)
            self._refresh_from_payment()
        except Exception as e:
            QMessageBox.warning(self, 'Query', str(e))

    def _confirm_match(self):
        if not self._ensure_payment():
            return
        ref = self.match_pick.currentData() or ''
        if not ref:
            # parse from text
            text = self.match_pick.currentText()
            ref = text.split('·')[0].strip() if text else ''
        if not ref:
            QMessageBox.warning(self, 'Confirm', 'Select a match candidate.')
            return
        try:
            self.payment = self.svc.confirm_match(
                self.payment.id, ref, confirmed_by=self.cashier_name or 'cashier'
            )
            self._refresh_from_payment()
        except Exception as e:
            QMessageBox.warning(self, 'Confirm', str(e))

    def _accept_underpay(self):
        if not self._ensure_payment():
            return
        p = self.svc.get_payment(self.payment.id) or self.payment
        if p.status != PaymentStatus.UNDERPAID.value:
            QMessageBox.warning(self, 'Underpay', 'Payment is not underpaid.')
            return
        reply = QMessageBox.question(
            self, 'Accept underpayment',
            f'Customer paid {self.currency} {float(p.amount_received or 0):,.2f} '
            f'(expected {p.amount_expected:,.2f}).\n\n'
            'Accept as part payment and continue? Remaining balance must be handled as debt.',
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self.payment = self.svc.accept_underpayment_as_part(
                p.id, confirmed_by=self.cashier_name or 'cashier',
            )
            self._refresh_from_payment()
            if self.payment.status == PaymentStatus.VERIFIED.value:
                self.accept()
        except Exception as e:
            QMessageBox.warning(self, 'Underpay', str(e))

    def _on_poll(self):
        if not self.payment:
            self._poll.stop()
            return
        try:
            if self.payment.checkout_request_id:
                self.payment = self.svc.query_payment(self.payment.id)
            else:
                self.payment = self.svc.sync_incoming_and_match(self.payment.id)
            self._refresh_from_payment()
            if self.payment.status in (
                PaymentStatus.VERIFIED.value,
                PaymentStatus.COMPLETED.value,
                PaymentStatus.FAILED.value,
                PaymentStatus.EXPIRED.value,
                PaymentStatus.CANCELLED.value,
            ):
                self._poll.stop()
        except Exception:
            pass

    def _finish(self):
        if not self.payment:
            return
        p = self.svc.get_payment(self.payment.id) or self.payment
        if p.status == PaymentStatus.OVERPAID.value:
            reply = QMessageBox.question(
                self, 'Overpayment',
                f'Customer paid {self.currency} {p.amount_received:,.2f} '
                f'(expected {p.amount_expected:,.2f}). Accept and complete sale?',
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            p = self.svc.accept_overpayment(p.id, confirmed_by=self.cashier_name or 'cashier')
        if p.status != PaymentStatus.VERIFIED.value:
            QMessageBox.warning(
                self, 'Not verified',
                f'Payment status is {p.status}. Sale cannot be created until VERIFIED.',
            )
            return
        self.payment = p
        self.accept()

    def closeEvent(self, event):
        self._poll.stop()
        super().closeEvent(event)


def run_mpesa_checkout(parent, **kwargs) -> Optional[PaymentRecord]:
    dlg = MpesaCheckoutDialog(parent, **kwargs)
    if dlg.exec_() == QDialog.Accepted:
        return dlg.payment
    return None
