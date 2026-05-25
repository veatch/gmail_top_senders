"""Local web interface for Gmail sender analytics."""

from urllib.parse import urlencode

from flask import Flask, g, render_template, request

from gmail_top_senders import db
from gmail_top_senders.report import _format_bytes, _format_date


PAGE_SIZE = 20
SENDER_PAGE_SIZE = 50


def _toggle_param(args, key, value):
    """Return a query string with ``key`` toggled to ``value``, or removed if already set."""
    d = {k: v for k, v in args.items() if k != key}
    if args.get(key) != value:
        d[key] = value
    return ("?" + urlencode(d)) if d else ""


def _set_param(args, key, value):
    """Return a query string with ``key`` set to ``value``, preserving all other params."""
    d = dict(args)
    d[key] = value
    return "?" + urlencode(d)


def create_app(db_path):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    app.jinja_env.filters["format_bytes"] = _format_bytes
    app.jinja_env.filters["format_date"] = _format_date

    def get_db():
        if "db" not in g:
            conn = db.connect(app.config["DB_PATH"])
            db.init_schema(conn)
            g.db = conn
        return g.db

    @app.teardown_appcontext
    def close_db(e=None):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.route("/")
    def messages():
        show_deleted = request.args.get("show_deleted") == "1"
        subject = request.args.get("subject", "").strip() or None

        try:
            limit = int(request.args.get("limit", PAGE_SIZE))
            if limit < 1:
                limit = PAGE_SIZE
        except (ValueError, TypeError):
            limit = PAGE_SIZE

        all_rows = db.all_messages(get_db(), include_deleted=show_deleted, subject_filter=subject)
        total_messages = len(all_rows)
        total_size = sum(r[3] for r in all_rows)
        rows = all_rows[:limit]

        toggle_deleted = _toggle_param(request.args, "show_deleted", "1")
        load_more_url = _set_param(request.args, "limit", limit + PAGE_SIZE) if limit < total_messages else None
        show_all_url = _set_param(request.args, "limit", total_messages) if limit < total_messages else None

        return render_template("messages.html",
            rows=rows,
            show_deleted=show_deleted,
            subject=subject or "",
            total_messages=total_messages,
            total_size=total_size,
            toggle_deleted=toggle_deleted,
            load_more_url=load_more_url,
            show_all_url=show_all_url,
        )

    @app.route("/senders")
    def senders():
        group_by = request.args.get("group_by", "address")
        if group_by not in ("address", "display-name"):
            group_by = "address"
        order_by = request.args.get("order_by", "remaining-size")
        if order_by not in ("remaining-size", "total-size", "sender", "message-count", "avg-size"):
            order_by = "remaining-size"
        show_deleted = request.args.get("show_deleted") == "1"
        subject = request.args.get("subject", "").strip() or None

        try:
            limit = int(request.args.get("limit", PAGE_SIZE))
            if limit < 1:
                limit = PAGE_SIZE
        except (ValueError, TypeError):
            limit = PAGE_SIZE

        all_rows = db.aggregate_by_sender(
            get_db(), group_by, order_by,
            include_deleted=show_deleted, subject_filter=subject,
        )
        total_senders = len(all_rows)
        total_msgs = sum(r[1] for r in all_rows)
        total_size = sum(r[2] for r in all_rows)
        rows = all_rows[:limit]

        toggle_deleted = _toggle_param(request.args, "show_deleted", "1")
        load_more_url = _set_param(request.args, "limit", limit + PAGE_SIZE) if limit < total_senders else None
        show_all_url = _set_param(request.args, "limit", total_senders) if limit < total_senders else None

        return render_template("senders.html",
            rows=rows,
            group_by=group_by,
            order_by=order_by,
            show_deleted=show_deleted,
            subject=subject or "",
            total_msgs=total_msgs,
            total_size=total_size,
            total_senders=total_senders,
            toggle_deleted=toggle_deleted,
            load_more_url=load_more_url,
            show_all_url=show_all_url,
        )

    @app.route("/sender/<path:sender>")
    def sender_detail(sender):
        show_deleted = request.args.get("show_deleted") == "1"
        subject = request.args.get("subject", "").strip() or None

        try:
            limit = int(request.args.get("limit", SENDER_PAGE_SIZE))
            if limit < 1:
                limit = SENDER_PAGE_SIZE
        except (ValueError, TypeError):
            limit = SENDER_PAGE_SIZE

        all_rows = db.messages_by_sender(
            get_db(), sender, top_n=None,
            include_deleted=show_deleted, subject_filter=subject,
        )
        total_messages = len(all_rows)
        total_size = sum(r[3] for r in all_rows)
        rows = all_rows[:limit]

        toggle_deleted = _toggle_param(request.args, "show_deleted", "1")
        load_more_url = _set_param(request.args, "limit", limit + SENDER_PAGE_SIZE) if limit < total_messages else None
        show_all_url = _set_param(request.args, "limit", total_messages) if limit < total_messages else None

        return render_template("sender.html",
            sender=sender,
            rows=rows,
            show_deleted=show_deleted,
            subject=subject or "",
            total_size=total_size,
            total_messages=total_messages,
            toggle_deleted=toggle_deleted,
            load_more_url=load_more_url,
            show_all_url=show_all_url,
        )

    @app.route("/message/<message_id>/mark-deleted", methods=["POST"])
    def mark_message_as_deleted(message_id):
        db.mark_deleted(get_db(), message_id)
        return "", 204

    @app.route("/message/<message_id>/keep", methods=["POST"])
    def keep_message(message_id):
        kept = (request.get_json(silent=True) or {}).get("kept", True)
        db.mark_kept(get_db(), message_id, bool(kept))
        return "", 204

    return app
