import json

from app.db import get_db
from app.services.dependencies import evaluate_batch, record_check
from app.services.objects import ServiceError


def get_close_run(batch_id: int, db_path: str | None = None) -> dict | None:
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM close_runs WHERE batch_id=?", (batch_id,)
        ).fetchone()
        return dict(row) if row else None


def close_batch(batch_id: int, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        # 提交瞬间取写锁：判定与闭合在同一事务内同源读写，
        # 两名调度同点闭合时只有一个能放行，不会双成功入账。
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute(
            "SELECT * FROM landing_batches WHERE id=?", (batch_id,)
        ).fetchone()
        if not batch:
            raise ServiceError("批次不存在", 404)
        if batch["status"] == "已闭合":
            raise ServiceError("批次已闭合", 409)
        if batch["status"] != "收集中":
            raise ServiceError("仅收集中批次可闭合", 409)
        objs = conn.execute(
            "SELECT id FROM landing_objects WHERE batch_id=? AND status='已登记'",
            (batch_id,),
        ).fetchall()
        if not objs:
            raise ServiceError("空批不可闭合", 400)
        # 路径已定：提交瞬间重取依赖（不用打开瞬间的冻结快照放行）。
        # 与依赖面板同用一个 evaluate_batch，判定与闭合天然同源。
        dep = evaluate_batch(conn, dict(batch))
        if not dep["ready"]:
            record_check(conn, batch_id, "close", dep)
            conn.commit()  # 被拦的判定也留痕，供回放
            raise ServiceError(dep["message"], 409)
        n = len(objs)
        detail = json.dumps(
            {"message": f"闭合 {n} 个对象", "dependencies": dep},
            ensure_ascii=False,
        )
        conn.execute(
            "UPDATE landing_batches SET status='已闭合', closed_object_count=? WHERE id=?",
            (n, batch_id),
        )
        conn.execute(
            "UPDATE landing_objects SET status='已闭合' WHERE batch_id=? AND status='已登记'",
            (batch_id,),
        )
        cur = conn.execute(
            "INSERT INTO close_runs(batch_id, object_count, ok, detail) VALUES (?,?,1,?)",
            (batch_id, n, detail),
        )
        record_check(conn, batch_id, "close", dep, run_id=cur.lastrowid)
        run = conn.execute(
            "SELECT * FROM close_runs WHERE batch_id=?", (batch_id,)
        ).fetchone()
        return dict(run)
