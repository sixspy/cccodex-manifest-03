import json
from datetime import datetime, timezone

from app.config import Config
from app.db import get_db


def zone_prefix(zone_code: str) -> str:
    return (zone_code or "").split("_")[0]


def evaluate_batch(conn, batch: dict) -> dict:
    """跨区依赖判定（全系统唯一判定源）。

    依赖面板、批次列表徽标、闭合放行三处都走这一个函数，
    保证「判定与闭合同源」。闭合路径在 BEGIN IMMEDIATE 事务内调用，
    即「提交瞬间重取」；面板路径是打开瞬间的只读快照，不作放行依据。
    """
    prefix = zone_prefix(batch["zone_code"])
    dep_prefixes = list(Config.ZONE_DEPENDENCIES.get(prefix, []))
    pending = []
    if dep_prefixes:
        rows = conn.execute(
            "SELECT id, zone_code, zone_name, biz_date, status FROM landing_batches "
            "WHERE biz_date <= ? AND id != ? ORDER BY biz_date, id",
            (batch["biz_date"], batch["id"]),
        ).fetchall()
        for r in rows:
            if zone_prefix(r["zone_code"]) not in dep_prefixes:
                continue
            if r["status"] == "已闭合":
                continue
            cnt = conn.execute(
                "SELECT COUNT(*) AS c FROM landing_objects "
                "WHERE batch_id=? AND status='已登记'",
                (r["id"],),
            ).fetchone()["c"]
            pending.append({**dict(r), "registered_objects": cnt})
    ready = not pending
    if ready:
        message = "依赖齐套，可闭合" if dep_prefixes else "本区无跨区依赖，可闭合"
    else:
        names = "、".join(f"{p['zone_name']}({p['biz_date']})" for p in pending)
        message = f"依赖未齐套：{names} 还没闭合，本批暂不可闭合"
    return {
        "ready": ready,
        "label": "齐套" if ready else "未齐套",
        "required_zones": dep_prefixes,
        "pending": pending,
        "pending_count": len(pending),
        "message": message,
        "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_dependencies(batch_id: int, db_path: str | None = None) -> dict:
    """依赖面板读路径：打开瞬间的只读快照，不落库。"""
    with get_db(db_path) as conn:
        batch = conn.execute(
            "SELECT * FROM landing_batches WHERE id=?", (batch_id,)
        ).fetchone()
        if not batch:
            return {}
        return evaluate_batch(conn, dict(batch))


def record_check(
    conn, batch_id: int, source: str, ev: dict, run_id: int | None = None
) -> None:
    """闭合路径的判定留痕（含被拦的），供判定回放。"""
    conn.execute(
        "INSERT INTO dependency_checks(batch_id, source, ready, pending_count, detail, run_id) "
        "VALUES (?,?,?,?,?,?)",
        (
            batch_id,
            source,
            1 if ev["ready"] else 0,
            ev["pending_count"],
            json.dumps(ev, ensure_ascii=False),
            run_id,
        ),
    )


def list_checks(batch_id: int, db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM dependency_checks WHERE batch_id=? ORDER BY id DESC LIMIT 10",
            (batch_id,),
        ).fetchall()
        return [dict(r) for r in rows]
