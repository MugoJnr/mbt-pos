"""HTTP routes for the shop M-Pesa ledger. The browser never receives secrets."""
from __future__ import annotations

from flask import g, jsonify, request

from backend.mpesa_service import (
    MpesaSaleError,
    authenticate_profile,
    can_configure,
    can_operate,
    can_override,
    can_view,
    connect,
    create_profile,
    diagnostics,
    list_incoming,
    list_payments,
    list_profiles,
    match_incoming,
    poll_payment,
    record_incoming,
    release_unknown,
    save_service_token,
    set_profile_status,
    start_stk,
    summary,
)


def register(app, token_required):
    def _db():
        return connect()

    def _actor():
        return g.current_user or {}

    def _run(func, *args, commit=False):
        db = _db()
        try:
            result = func(db, _actor(), *args)
            if commit:
                db.commit()
            return jsonify(result)
        except MpesaSaleError as exc:
            db.rollback()
            return jsonify({"error": str(exc)}), 400
        finally:
            db.close()

    @app.route("/api/mpesa/diagnostics", methods=["GET"])
    @token_required
    def mpesa_diagnostics():
        if not (can_view(_actor()) or can_operate(_actor())):
            return jsonify({"error": "You cannot view M-Pesa diagnostics."}), 403
        return _run(diagnostics, commit=True)

    @app.route("/api/mpesa/summary", methods=["GET"])
    @token_required
    def mpesa_summary():
        if not can_view(_actor()):
            return jsonify({"error": "You cannot view M-Pesa totals."}), 403
        return _run(summary)

    @app.route("/api/mpesa/profiles", methods=["GET"])
    @token_required
    def mpesa_profiles():
        if not can_operate(_actor()):
            return jsonify({"error": "You cannot view M-Pesa profiles."}), 403
        return _run(lambda db, actor: {"profiles": list_profiles(db, actor)})

    @app.route("/api/mpesa/profiles", methods=["POST"])
    @token_required
    def mpesa_create_profile():
        if not can_configure(_actor()):
            return jsonify({"error": "Only an admin can save a merchant profile."}), 403
        body = request.json or {}
        return _run(lambda db, actor: create_profile(db, actor, body), commit=True)

    @app.route("/api/mpesa/profiles/<profile_id>/activate", methods=["POST"])
    @token_required
    def mpesa_activate(profile_id):
        if not can_configure(_actor()):
            return jsonify({"error": "Only an admin can change a merchant profile."}), 403
        body = request.json or {}
        return _run(
            lambda db, actor: set_profile_status(
                db, actor, profile_id, True, bool(body.get("make_default"))
            ),
            commit=True,
        )

    @app.route("/api/mpesa/profiles/<profile_id>/deactivate", methods=["POST"])
    @token_required
    def mpesa_deactivate(profile_id):
        if not can_configure(_actor()):
            return jsonify({"error": "Only an admin can change a merchant profile."}), 403
        return _run(lambda db, actor: set_profile_status(db, actor, profile_id, False), commit=True)

    @app.route("/api/mpesa/profiles/<profile_id>/authenticate", methods=["POST"])
    @token_required
    def mpesa_authenticate(profile_id):
        if not can_view(_actor()):
            return jsonify({"error": "You cannot test this profile."}), 403
        return _run(lambda db, actor: authenticate_profile(db, actor, profile_id))

    @app.route("/api/mpesa/service-token", methods=["PUT"])
    @token_required
    def mpesa_service_token():
        if not can_configure(_actor()):
            return jsonify({"error": "Only an admin can save the service token."}), 403
        token = str((request.json or {}).get("service_token") or "")
        if len(token.strip()) < 8:
            return jsonify({"error": "Enter the payment service token."}), 400
        save_service_token(token)
        return jsonify({"success": True, "token_configured": True, "token_returned": False})

    @app.route("/api/mpesa/stk", methods=["POST"])
    @token_required
    def mpesa_stk():
        if not can_operate(_actor()):
            return jsonify({"error": "You cannot send a phone prompt."}), 403
        body = request.json or {}
        return _run(lambda db, actor: start_stk(
            db, actor,
            phone=str(body.get("phone") or ""),
            amount=body.get("amount"),
            profile_id=str(body.get("profile_id") or ""),
            sale_reference=str(body.get("sale_reference") or "SALE"),
            idempotency_key=str(body.get("idempotency_key") or ""),
            new_attempt_of=str(body.get("new_attempt_of") or ""),
        ))

    @app.route("/api/mpesa/payments/<payment_id>/poll", methods=["POST"])
    @token_required
    def mpesa_poll(payment_id):
        if not can_operate(_actor()):
            return jsonify({"error": "You cannot check this payment."}), 403
        return _run(lambda db, actor: poll_payment(db, actor, payment_id))

    @app.route("/api/mpesa/payments/<payment_id>/release", methods=["POST"])
    @token_required
    def mpesa_release(payment_id):
        if not can_override(_actor()):
            return jsonify({"error": "A manager must release an unknown payment."}), 403
        reason = str((request.json or {}).get("reason") or "")
        return _run(lambda db, actor: release_unknown(db, actor, payment_id, reason))

    @app.route("/api/mpesa/payments", methods=["GET"])
    @token_required
    def mpesa_payments():
        if not can_operate(_actor()):
            return jsonify({"error": "You cannot view M-Pesa payments."}), 403
        filters = {
            "state": request.args.get("state") or "",
            "verification": request.args.get("verification") or "",
            "profile_id": request.args.get("profile_id") or "",
            "kind": request.args.get("kind") or "",
        }
        return _run(lambda db, actor: {"payments": list_payments(db, actor, **filters)})

    @app.route("/api/mpesa/incoming", methods=["GET"])
    @token_required
    def mpesa_incoming_list():
        if not can_view(_actor()):
            return jsonify({"error": "You cannot view incoming payments."}), 403
        return _run(lambda db, actor: {"incoming": list_incoming(db, actor)})

    @app.route("/api/mpesa/incoming", methods=["POST"])
    @token_required
    def mpesa_incoming_create():
        if not can_override(_actor()):
            return jsonify({"error": "A manager records an incoming payment."}), 403
        return _run(lambda db, actor: record_incoming(db, actor, request.json or {}), commit=True)

    @app.route("/api/mpesa/incoming/<incoming_id>/match", methods=["POST"])
    @token_required
    def mpesa_incoming_match(incoming_id):
        if not can_override(_actor()):
            return jsonify({"error": "A manager matches an incoming payment."}), 403
        body = request.json or {}
        try:
            sale_id = int(body.get("sale_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "Choose the sale to match."}), 400
        return _run(
            lambda db, actor: match_incoming(db, actor, incoming_id, sale_id, str(body.get("reason") or "")),
            commit=True,
        )
