"""HTTP routes for the Business Health & Issues Centre."""
from __future__ import annotations

from flask import g, jsonify, request

from desktop.utils.business_issues import (
    can_see,
    dismiss_issue,
    issue_events,
    list_issues,
    registry,
    scan,
    set_rule_mode,
    snooze_issue,
    summary,
)


def register_issue_routes(web) -> None:
    from web.web_routes import _get_db

    def _user():
        return g.current_user or {}

    @web.route("/api/issues/rules", methods=["GET"])
    def issue_rules():
        from backend.app import token_required

        @token_required
        def _inner():
            if not can_see(_user(), "stock"):
                return jsonify({"error": "You cannot view issue rules."}), 403
            db = _get_db()
            try:
                rows = registry()
                from desktop.utils.business_issues import rule_mode
                for row in rows:
                    row["mode"] = rule_mode(db, row["code"])
                return jsonify({"rules": rows})
            finally:
                db.close()

        return _inner()

    @web.route("/api/issues/rules/<code>", methods=["POST"])
    def issue_rule_mode(code):
        from backend.app import token_required

        @token_required
        def _inner():
            role = str((_user().get("role") or "")).lower()
            if role != "superadmin":
                return jsonify({"error": "Only a super admin can change an issue rule."}), 403
            body = request.get_json(silent=True) or {}
            db = _get_db()
            try:
                result = set_rule_mode(
                    db, code, str(body.get("mode") or ""),
                    str(_user().get("username") or "superadmin"),
                )
                return jsonify(result), int(result.get("status") or 200)
            finally:
                db.close()

        return _inner()

    @web.route("/api/issues/scan", methods=["POST"])
    def issue_scan():
        from backend.app import token_required

        @token_required
        def _inner():
            if not can_see(_user(), "stock"):
                return jsonify({"error": "You cannot scan business issues."}), 403
            db = _get_db()
            try:
                result = scan(db, str(_user().get("username") or "web"))
                result["summary"] = summary(db, _user())
                return jsonify(result)
            finally:
                db.close()

        return _inner()

    @web.route("/api/issues", methods=["GET"])
    def issue_list():
        from backend.app import token_required

        @token_required
        def _inner():
            if not can_see(_user(), "stock"):
                return jsonify({"error": "You cannot view business issues."}), 403
            status = (request.args.get("status") or "open").strip().lower()
            if status not in ("open", "resolved", "dismissed", "snoozed", "all"):
                status = "open"
            db = _get_db()
            try:
                if request.args.get("scan") == "1":
                    scan(db, str(_user().get("username") or "web"))
                include = request.args.get("shadow") == "1"
                items = list_issues(db, _user(), status, include_shadow=include)
                return jsonify({"issues": items, "summary": summary(db, _user())})
            finally:
                db.close()

        return _inner()

    @web.route("/api/issues/summary", methods=["GET"])
    def issue_summary():
        from backend.app import token_required

        @token_required
        def _inner():
            if not can_see(_user(), "stock"):
                return jsonify({"open": 0, "info": 0, "attention": 0, "important": 0, "critical": 0})
            db = _get_db()
            try:
                return jsonify(summary(db, _user()))
            finally:
                db.close()

        return _inner()

    @web.route("/api/issues/<int:issue_id>/events", methods=["GET"])
    def issue_history(issue_id):
        from backend.app import token_required

        @token_required
        def _inner():
            db = _get_db()
            try:
                items = list_issues(db, _user(), "all", include_shadow=True)
                if not any(item["id"] == issue_id for item in items):
                    return jsonify({"error": "You cannot view this issue."}), 403
                return jsonify({"events": issue_events(db, issue_id)})
            finally:
                db.close()

        return _inner()

    @web.route("/api/issues/<int:issue_id>/dismiss", methods=["POST"])
    def issue_dismiss(issue_id):
        from backend.app import token_required

        @token_required
        def _inner():
            body = request.get_json(silent=True) or {}
            db = _get_db()
            try:
                result = dismiss_issue(db, _user(), issue_id, str(body.get("reason") or ""))
                return jsonify(result), int(result.get("status") or 200)
            finally:
                db.close()

        return _inner()

    @web.route("/api/issues/<int:issue_id>/snooze", methods=["POST"])
    def issue_snooze(issue_id):
        from backend.app import token_required

        @token_required
        def _inner():
            body = request.get_json(silent=True) or {}
            db = _get_db()
            try:
                result = snooze_issue(
                    db, _user(), issue_id, body.get("days") or 1, str(body.get("reason") or ""),
                )
                return jsonify(result), int(result.get("status") or 200)
            finally:
                db.close()

        return _inner()
