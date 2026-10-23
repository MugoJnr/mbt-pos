"""Unmatched till and paybill credits. Ambiguous amounts are not auto-matched."""
from __future__ import annotations


class PaymentInbox:
    def __init__(self):
        self._credits: dict[str, dict] = {}
        self._open_sales: list[dict] = []

    def add_open_sale(self, sale_id: int, amount: float, receipt: str) -> None:
        self._open_sales.append({
            'sale_id': sale_id,
            'amount': round(float(amount), 2),
            'receipt': receipt,
        })

    def add_credit(self, credit_id: str, amount: float, reference: str) -> dict:
        credit_id = str(credit_id).strip()
        if credit_id in self._credits:
            return {'success': True, 'duplicate': True, 'status': self._credits[credit_id]['status']}
        amount = round(float(amount), 2)
        matches = [s for s in self._open_sales if abs(s['amount'] - amount) < 0.009]
        status = 'unmatched'
        sale_id = None
        if len(matches) == 1:
            status = 'matched'
            sale_id = matches[0]['sale_id']
        elif len(matches) > 1:
            status = 'ambiguous'
        self._credits[credit_id] = {
            'id': credit_id,
            'amount': amount,
            'reference': reference,
            'status': status,
            'sale_id': sale_id,
        }
        return {'success': True, 'status': status, 'sale_id': sale_id, 'sale_created': False}

    def reconcile(self, credit_id: str, sale_id: int) -> dict:
        row = self._credits.get(credit_id)
        if not row:
            return {'error': 'Credit was not found'}
        if row['status'] == 'reconciled':
            return {'success': True, 'duplicate': True, 'sale_id': row['sale_id']}
        if row['status'] == 'ambiguous' and sale_id is None:
            return {'error': 'Choose the sale. This credit matches more than one.'}
        row['status'] = 'reconciled'
        row['sale_id'] = sale_id
        return {'success': True, 'sale_id': sale_id, 'sale_created': False}
