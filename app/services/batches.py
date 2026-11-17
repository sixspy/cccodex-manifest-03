from app.db import get_db
from app.services.dependencies import evaluate_batch


def _row(r) -> dict:
    return dict(r) if r is not None else {}


def _with_dep(conn, d: dict) -> dict:
    """批次列表行的依赖徽标，与闭合判定同源（同一个 evaluate_batch）。"""
    ev = evaluate_batch(conn, d)
    d["dep_ready"] = ev["ready"]
    d["dep_pending"] = ev["pending_count"]
    d["dep_label"] = ev["label"] if ev["required_zones"] else "无依赖"
    return d


def list_batches(db_path: str | None = None, status: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM landing_batches WHERE status=? ORDER BY id",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM landing_batches ORDER BY id"
            ).fetchall()
        return [_with_dep(conn, dict(r)) for r in rows]


def get_batch(batch_id: int, db_path: str | None = None) -> dict | None:
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM landing_batches WHERE id=?", (batch_id,)
        ).fetchone()
        return _row(row) or None
