"""Local M-Pesa code and phone capture. No network call and no sale."""
from __future__ import annotations

import uuid


class LocalCheckout:
    def __init__(self):
        self._sessions: dict[str, dict] = {}

    def start(self, code: str, phone: str) -> dict:
        code = (code or '').strip()
        phone = (phone or '').strip()
        if not code or not phone:
            return {'error': 'Enter the payment code and phone number'}
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = {
            'id': session_id,
            'code': code,
            'phone': phone,
            'status': 'pending',
            'sale_id': None,
        }
        return {'success': True, 'id': session_id, 'status': 'pending', 'sale_created': False}

    def mark_uncertain(self, session_id: str) -> dict:
        row = self._sessions.get(session_id)
        if not row:
            return {'error': 'Payment session was not found'}
        if row['status'] in ('accepted', 'rejected'):
            return {'error': 'This payment is already decided', 'status': row['status']}
        row['status'] = 'uncertain'
        return {'success': True, 'status': 'uncertain', 'sale_created': False}

    def accept(self, session_id: str) -> dict:
        row = self._sessions.get(session_id)
        if not row:
            return {'error': 'Payment session was not found'}
        if row['status'] == 'accepted':
            return {'success': True, 'duplicate': True, 'status': 'accepted', 'sale_created': False}
        if row['status'] != 'pending':
            return {'error': 'Only a pending payment can be accepted', 'status': row['status']}
        row['status'] = 'accepted'
        return {'success': True, 'status': 'accepted', 'sale_created': False}

    def reject(self, session_id: str) -> dict:
        row = self._sessions.get(session_id)
        if not row:
            return {'error': 'Payment session was not found'}
        if row['status'] == 'accepted':
            return {'error': 'An accepted payment cannot be rejected'}
        row['status'] = 'rejected'
        return {'success': True, 'status': 'rejected', 'sale_created': False}
