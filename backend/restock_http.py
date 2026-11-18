"""HTTP routes for restocking requests. Stock is never changed here except by the existing delivery API."""
from __future__ import annotations

from flask import g, jsonify, request


def _actor():
    user = g.current_user or {}
    return {
        "id": user.get("id"),
        "username": user.get("full_name") or user.get("username") or "",
        "role": (user.get("role") or "").lower(),
        "shop_id": user.get("shop_id") or "local",
    }


def _db():
    from desktop.utils.api_client import _db
    return _db()


def _finish(conn, result):
    status = int(result.pop("status", 0) or (400 if result.get("error") else 200))
    if result.get("success"):
        conn.commit()
    else:
        conn.rollback()
    return jsonify(result), status


def register_restock_routes(web):
    @web.route("/api/restock-requests", methods=["GET", "POST"])
    def restock_collection():
        from backend.app import token_required

        @token_required
        def _inner():
            from backend import restock_requests as restock
            conn = _db()
            try:
                actor = _actor()
                if request.method == "POST":
                    result = restock.create_request(conn, actor, request.json or {})
                else:
                    result = restock.list_requests(conn, actor, request.args)
                return _finish(conn, result)
            finally:
                conn.close()

        return _inner()

    @web.route("/api/restock-requests/suggestions", methods=["GET"])
    def restock_suggestions():
        from backend.app import token_required

        @token_required
        def _inner():
            from backend import restock_requests as restock
            conn = _db()
            try:
                return _finish(conn, restock.suggestions(conn, _actor()))
            finally:
                conn.close()

        return _inner()

    @web.route("/api/restock-requests/buyers", methods=["GET"])
    def restock_buyers():
        from backend.app import token_required

        @token_required
        def _inner():
            from backend import restock_requests as restock
            conn = _db()
            try:
                return _finish(conn, restock.buyers(conn, _actor()))
            finally:
                conn.close()

        return _inner()

    @web.route("/api/restock-requests/products", methods=["GET"])
    def restock_products():
        from backend.app import token_required

        @token_required
        def _inner():
            from backend import restock_requests as restock
            conn = _db()
            try:
                return _finish(conn, restock.search_products(conn, _actor(), request.args.get("q") or ""))
            finally:
                conn.close()

        return _inner()

    @web.route("/api/restock-requests/<int:request_id>", methods=["GET", "PUT"])
    def restock_one(request_id):
        from backend.app import token_required

        @token_required
        def _inner():
            from backend import restock_requests as restock
            conn = _db()
            try:
                actor = _actor()
                if request.method == "PUT":
                    result = restock.update_request(conn, actor, request_id, request.json or {})
                else:
                    result = restock.get_request(conn, actor, request_id)
                return _finish(conn, result)
            finally:
                conn.close()

        return _inner()

    @web.route("/api/restock-requests/<int:request_id>/lines", methods=["POST"])
    def restock_add_line(request_id):
        from backend.app import token_required

        @token_required
        def _inner():
            from backend import restock_requests as restock
            conn = _db()
            try:
                return _finish(conn, restock.add_line(conn, _actor(), request_id, request.json or {}))
            finally:
                conn.close()

        return _inner()

    @web.route("/api/restock-requests/<int:request_id>/lines/<int:line_id>", methods=["PUT", "DELETE"])
    def restock_line(request_id, line_id):
        from backend.app import token_required

        @token_required
        def _inner():
            from backend import restock_requests as restock
            conn = _db()
            try:
                payload = request.json or {}
                if request.method == "DELETE":
                    result = restock.remove_line(conn, _actor(), request_id, line_id, request.args.get("version") or payload.get("version"))
                else:
                    result = restock.update_line(conn, _actor(), request_id, line_id, payload)
                return _finish(conn, result)
            finally:
                conn.close()

        return _inner()

    def _action(request_id, method_name):
        from backend.app import token_required

        @token_required
        def _inner():
            from backend import restock_requests as restock
            conn = _db()
            try:
                payload = request.json or {}
                fn = getattr(restock, method_name)
                if method_name in ("submit_request", "return_to_draft", "archive_request", "reopen_request"):
                    result = fn(conn, _actor(), request_id, payload.get("version"))
                else:
                    result = fn(conn, _actor(), request_id, payload)
                return _finish(conn, result)
            finally:
                conn.close()

        return _inner()

    @web.route("/api/restock-requests/<int:request_id>/submit", methods=["POST"])
    def restock_submit(request_id):
        return _action(request_id, "submit_request")

    @web.route("/api/restock-requests/<int:request_id>/return-to-draft", methods=["POST"])
    def restock_redraft(request_id):
        return _action(request_id, "return_to_draft")

    @web.route("/api/restock-requests/<int:request_id>/assign", methods=["POST"])
    def restock_assign(request_id):
        return _action(request_id, "assign_request")

    @web.route("/api/restock-requests/<int:request_id>/purchase", methods=["POST"])
    def restock_purchase(request_id):
        return _action(request_id, "record_purchase")

    @web.route("/api/restock-requests/<int:request_id>/link-receipt", methods=["POST"])
    def restock_link(request_id):
        return _action(request_id, "link_receipt")

    @web.route("/api/restock-requests/<int:request_id>/receive", methods=["POST"])
    def restock_receive(request_id):
        from backend.app import token_required

        @token_required
        def _inner():
            from backend import restock_requests as restock
            from desktop.utils.api_client import APIClient
            from desktop.utils.security import has_permission
            actor = _actor()
            if not (has_permission(actor, "restock.manage") and has_permission(actor, "inventory.receive")):
                return jsonify({"error": "You cannot receive goods for this list."}), 403
            payload = request.json or {}
            conn = _db()
            try:
                preview = restock.get_request(conn, actor, request_id)
                if preview.get("error"):
                    return _finish(conn, preview)
                line_id = int(payload.get("line_id"))
                lines = preview["request"].get("working_lines") or preview["request"].get("lines") or []
                match = next((line for line in lines if int(line.get("line_id") or line.get("id")) == line_id), None)
                if not match:
                    return _finish(conn, {"error": "That product is not on this list.", "status": 400})
                api = APIClient()
                api._role = actor["role"]
                api._user_id = actor["id"]
                api._username = actor["username"]
                received = api.receive_stock(
                    int(match["product_id"]),
                    payload.get("quantity"),
                    supplier_id=payload.get("supplier_id"),
                    notes=str(payload.get("notes") or "Restock list delivery"),
                    unit_cost=payload.get("unit_cost"),
                    client_token=str(payload.get("client_token") or ""),
                )
                if received.get("error"):
                    return jsonify(received), 400
                linked = restock.link_receipt(conn, actor, request_id, {
                    "line_id": line_id,
                    "receipt_id": received.get("receipt_id"),
                    "qty_accepted": payload.get("quantity"),
                    "qty_rejected": payload.get("qty_rejected") or 0,
                })
                linked["receipt_number"] = received.get("receipt_number")
                linked["stock_after"] = received.get("new_stock")
                return _finish(conn, linked)
            finally:
                conn.close()

        return _inner()

    @web.route("/api/restock-requests/<int:request_id>/cancel", methods=["POST"])
    def restock_cancel(request_id):
        return _action(request_id, "cancel_request")

    @web.route("/api/restock-requests/<int:request_id>/archive", methods=["POST"])
    def restock_archive(request_id):
        return _action(request_id, "archive_request")

    @web.route("/api/restock-requests/<int:request_id>/reopen", methods=["POST"])
    def restock_reopen(request_id):
        return _action(request_id, "reopen_request")

    @web.route("/api/restock-requests/<int:request_id>/duplicate", methods=["POST"])
    def restock_duplicate(request_id):
        from backend.app import token_required

        @token_required
        def _inner():
            from backend import restock_requests as restock
            conn = _db()
            try:
                return _finish(conn, restock.duplicate_request(conn, _actor(), request_id))
            finally:
                conn.close()

        return _inner()

    @web.route("/api/restock-requests/<int:request_id>/complete", methods=["POST"])
    def restock_complete(request_id):
        return _action(request_id, "complete_request")

    @web.route("/api/restock-requests/<int:request_id>/document", methods=["GET", "POST"])
    def restock_document(request_id):
        from backend.app import token_required

        @token_required
        def _inner():
            from backend import restock_requests as restock
            conn = _db()
            try:
                layout = str(request.args.get("format") or "html").lower()
                paper = str(request.args.get("paper") or "80")
                if layout == "thermal":
                    result = restock.document_text(conn, _actor(), request_id, paper)
                    return _finish(conn, result)
                if layout in ("pdf", "a4", "thermal-pdf"):
                    result = restock.document_pdf(
                        conn, _actor(), request_id,
                        "thermal" if layout == "thermal-pdf" else "a4",
                        paper,
                    )
                    if result.get("error"):
                        return _finish(conn, result)
                    from flask import Response
                    conn.commit()
                    filename = f"{result.get('reference') or 'restock'}.pdf"
                    return Response(
                        result["pdf"],
                        mimetype="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename={filename}"},
                    )
                result = restock.document_html(conn, _actor(), request_id)
                return _finish(conn, result)
            finally:
                conn.close()

        return _inner()
