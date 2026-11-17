import json
import threading

from app.db import get_db
from app.services import close_batch
from app.services.objects import ServiceError

BRONZE = ("bronze_orders", "bronze_payments", "bronze_events")


def _batch(authed, zone_code):
    items = authed.get("/api/batches").json()["items"]
    return next(b for b in items if b["zone_code"] == zone_code)


def _register(authed, bid, key):
    r = authed.post(
        f"/api/batches/{bid}/objects",
        json={"object_key": key, "content_hash": "h-" + key, "byte_size": 10},
    )
    assert r.status_code == 200


def _close_bronze_all(authed):
    for code in BRONZE:
        b = _batch(authed, code)
        _register(authed, b["id"], f"raw/{code}.parquet")
        r = authed.post(f"/api/batches/{b['id']}/close", json={})
        assert r.status_code == 200


def test_silver_blocked_until_bronze_ready(authed):
    silver = _batch(authed, "silver_events")
    # 批次列表徽标：未齐套
    assert silver["dep_ready"] is False
    assert silver["dep_label"] == "未齐套"
    assert silver["dep_pending"] == 3

    _register(authed, silver["id"], "raw/silver-events.parquet")

    # 依赖面板（打开瞬间快照）：未齐套，铜区三批欠账
    detail = authed.get(f"/api/batches/{silver['id']}").json()
    dep = detail["dependencies"]
    assert dep["label"] == "未齐套"
    assert dep["pending_count"] == 3
    assert {p["zone_code"] for p in dep["pending"]} == set(BRONZE)

    # 依赖未齐就闭合 → 拦下，白话说明
    r = authed.post(f"/api/batches/{silver['id']}/close", json={})
    assert r.status_code == 409
    err = r.json()["error"]
    assert "未齐套" in err
    assert "铜区" in err

    # 被拦后批次仍在收集中，判定留痕可回放
    assert _batch(authed, "silver_events")["status"] == "收集中"
    checks = authed.get(f"/api/batches/{silver['id']}/dependency-checks").json()["items"]
    assert len(checks) == 1
    assert checks[0]["ready"] == 0
    assert checks[0]["pending_count"] == 3

    # 铜区全部闭合后：面板亮齐套，放行闭合
    _close_bronze_all(authed)
    detail2 = authed.get(f"/api/batches/{silver['id']}").json()
    assert detail2["dependencies"]["label"] == "齐套"

    r2 = authed.post(f"/api/batches/{silver['id']}/close", json={})
    assert r2.status_code == 200
    run = r2.json()["run"]
    assert run["ok"] == 1
    # 闭合详情里带着提交瞬间的依赖快照，可回放
    snap = json.loads(run["detail"])["dependencies"]
    assert snap["ready"] is True
    assert snap["pending_count"] == 0

    # 回放：先被拦（未齐套）后放行（齐套），最新在前
    checks2 = authed.get(f"/api/batches/{silver['id']}/dependency-checks").json()["items"]
    assert [c["ready"] for c in checks2] == [1, 0]

    # 批次列表徽标同步翻齐套
    assert _batch(authed, "silver_events")["dep_label"] == "齐套"


def test_submit_time_refetch_governs_not_open_snapshot(authed):
    """路径验证：打开瞬间的冻结快照（未齐套）不放行也不拦死，
    提交瞬间重取到依赖已齐套即放行。"""
    silver = _batch(authed, "silver_events")
    _register(authed, silver["id"], "raw/silver-events.parquet")

    # 打开瞬间的冻结快照：未齐套
    snap = authed.get(f"/api/batches/{silver['id']}").json()["dependencies"]
    assert snap["ready"] is False

    # 另一调度把铜区依赖闭合了（面板未刷新，快照已过期）
    _close_bronze_all(authed)

    # 不重取面板直接提交：按提交瞬间重取放行
    r = authed.post(f"/api/batches/{silver['id']}/close", json={})
    assert r.status_code == 200
    assert r.json()["run"]["ok"] == 1


def test_concurrent_close_only_one_succeeds(authed):
    """两名调度同点闭合：加锁后只有一个成功入账，另一个拿白话 409。"""
    bronze = _batch(authed, "bronze_orders")
    _register(authed, bronze["id"], "raw/race.parquet")
    bid = bronze["id"]

    barrier = threading.Barrier(2)
    results = []

    def worker():
        barrier.wait()
        try:
            run = close_batch(bid)
            results.append(("ok", run["object_count"]))
        except ServiceError as exc:
            results.append(("err", exc.status_code))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(r[0] for r in results) == ["err", "ok"]
    err = next(r for r in results if r[0] == "err")
    assert err[1] == 409

    # 只入账一次
    with get_db() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM close_runs WHERE batch_id=?", (bid,)
        ).fetchone()["c"]
        assert n == 1
        row = conn.execute(
            "SELECT status, closed_object_count FROM landing_batches WHERE id=?", (bid,)
        ).fetchone()
        assert row["status"] == "已闭合"
        assert row["closed_object_count"] == 1


def test_bronze_has_no_cross_zone_dependency(authed):
    """铜区无跨区依赖：不受冻结约束，基线主链不变。"""
    bronze = _batch(authed, "bronze_payments")
    assert bronze["dep_label"] == "无依赖"
    _register(authed, bronze["id"], "raw/pay.parquet")
    r = authed.post(f"/api/batches/{bronze['id']}/close", json={})
    assert r.status_code == 200
