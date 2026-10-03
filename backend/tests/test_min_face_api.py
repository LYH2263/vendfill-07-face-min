"""最低陈列面端到端验收：货道卡、最新补货单、汇总栏按同一有效缺口出数。"""
import json
import os
import sqlite3
import tempfile

_DB_DIR = tempfile.mkdtemp(prefix="vendfill_test_")
DB_PATH = os.path.join(_DB_DIR, "test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH  # 须在导入 app 前设置

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402

from app.database import get_db, SessionLocal  # noqa: E402
from app.main import app, ensure_schema  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def by_slot(rows, slot):
    return next(r for r in rows if r["slot_no"] == slot)


def stored_order_lines(order_id):
    """直接读库，绕过 API（历史单没有查询接口）。"""
    con = sqlite3.connect(DB_PATH)
    try:
        row = con.execute("SELECT lines_json FROM refill_orders WHERE id=?", (order_id,)).fetchone()
        return json.loads(row[0])
    finally:
        con.close()


def test_initial_state_matches_current_net(client):
    lanes = client.get("/api/lanes?location_id=1").json()
    a1 = by_slot(lanes, "A1")
    assert a1["stock"] == 5 and a1["min_face"] == 0
    assert a1["gap"] == 15  # 现网口径：容量20 − 库存5 − 在途0


def test_set_min_face_rewrites_latest_order(client):
    first = client.post("/api/refills/run?location_id=1").json()
    a1_first = by_slot(first["lines"], "A1")
    assert a1_first["fill_qty"] == 15  # 只按库存 5 的口径

    a1_id = by_slot(client.get("/api/lanes?location_id=1").json(), "A1")["id"]
    resp = client.patch(f"/api/lanes/{a1_id}", json={"min_face": 8})
    assert resp.status_code == 200
    saved = resp.json()
    assert saved["min_face"] == 8 and saved["gap"] == 18
    assert saved["order_id"] == first["id"]  # 同提交重写最新单

    # 货道卡、最新单、汇总栏同数
    a1_lane = by_slot(client.get("/api/lanes?location_id=1").json(), "A1")
    latest = client.get("/api/refills/latest?location_id=1").json()
    a1_latest = by_slot(latest["lines"], "A1")
    summary = client.get("/api/refills/summary?location_id=1").json()
    assert latest["id"] == first["id"]  # 重写原单而非新单
    assert a1_latest["fill_qty"] == 18 > 15  # 高于只按库存 5 的口径
    assert a1_latest["gap"] == a1_lane["gap"] == 18
    assert summary["total_fill"] == latest["total_fill"] == first["total_fill"] - 15 + 18
    assert summary["need_fill_count"] == latest["need_fill_count"]


def test_elevated_lane_not_marked_full(client):
    # B2：容量15 库存10 在途5，现网缺口 0（满仓）；陈列面 12 抬出正补量
    b2_id = by_slot(client.get("/api/lanes?location_id=1").json(), "B2")["id"]
    resp = client.patch(f"/api/lanes/{b2_id}", json={"min_face": 12})
    assert resp.status_code == 200 and resp.json()["gap"] == 2

    latest = client.get("/api/refills/latest?location_id=1").json()
    b2 = by_slot(latest["lines"], "B2")
    assert b2["status"] == "need_fill" and b2["fill_qty"] == 2
    full_slots = [l["slot_no"] for l in client.get("/api/refills/full?location_id=1").json()["lanes"]]
    assert "B2" not in full_slots  # 待补与满仓互斥
    summary = client.get("/api/refills/summary?location_id=1").json()
    assert summary["full_count"] == sum(1 for l in latest["lines"] if l["status"] == "full")


def test_min_face_above_capacity_rejected(client):
    before_lanes = client.get("/api/lanes?location_id=1").json()
    before_latest = client.get("/api/refills/latest?location_id=1").json()
    a1 = by_slot(before_lanes, "A1")
    resp = client.patch(f"/api/lanes/{a1['id']}", json={"min_face": a1["capacity"] + 1})
    assert resp.status_code == 400
    # 三处不动
    assert client.get("/api/lanes?location_id=1").json() == before_lanes
    assert client.get("/api/refills/latest?location_id=1").json() == before_latest
    assert client.get("/api/refills/summary?location_id=1").json()["total_fill"] == before_latest["total_fill"]


def test_negative_min_face_rejected(client):
    a1 = by_slot(client.get("/api/lanes?location_id=1").json(), "A1")
    resp = client.patch(f"/api/lanes/{a1['id']}", json={"min_face": -1})
    assert resp.status_code == 400
    assert by_slot(client.get("/api/lanes?location_id=1").json(), "A1")["min_face"] == a1["min_face"]


def test_history_orders_not_rewritten(client):
    second = client.post("/api/refills/run?location_id=1").json()  # 再生成一单
    a1 = by_slot(client.get("/api/lanes?location_id=1").json(), "A1")
    resp = client.patch(f"/api/lanes/{a1['id']}", json={"min_face": 0})  # 回 0 = 现网口径
    assert resp.status_code == 200 and resp.json()["gap"] == 15

    latest = client.get("/api/refills/latest?location_id=1").json()
    assert latest["id"] == second["id"]
    assert by_slot(latest["lines"], "A1")["fill_qty"] == 15  # 最新单已按新口径重写
    history = stored_order_lines(1)  # 首单（非最新）不回刷，仍是陈列面 8 时的数
    assert by_slot(history["lines"], "A1")["fill_qty"] == 18


def test_blank_min_face_same_as_current(client):
    a1 = by_slot(client.get("/api/lanes?location_id=1").json(), "A1")
    resp = client.patch(f"/api/lanes/{a1['id']}", json={"min_face": None})
    assert resp.status_code == 200
    body = resp.json()
    assert body["min_face"] == 0 and body["gap"] == 15


def test_failed_save_rolls_back_lane_and_order(client):
    a1 = by_slot(client.get("/api/lanes?location_id=1").json(), "A1")
    before_latest = client.get("/api/refills/latest?location_id=1").json()

    def boom_get_db():
        db = SessionLocal()
        db.commit = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = boom_get_db
    try:
        resp = client.patch(f"/api/lanes/{a1['id']}", json={"min_face": 9})
        assert resp.status_code == 500
    finally:
        app.dependency_overrides.clear()

    # 陈列面与单全回改前
    a1_after = by_slot(client.get("/api/lanes?location_id=1").json(), "A1")
    assert a1_after["min_face"] == a1["min_face"] and a1_after["gap"] == a1["gap"]
    assert client.get("/api/refills/latest?location_id=1").json() == before_latest


def test_ensure_schema_migrates_old_table(tmp_path, monkeypatch):
    eng = create_engine("sqlite:///" + str(tmp_path / "old.db"))
    with eng.begin() as c:
        c.execute(text("CREATE TABLE lanes (id INTEGER PRIMARY KEY, location_id INTEGER,"
                       " slot_no VARCHAR(16), sku_name VARCHAR(64), capacity INTEGER,"
                       " stock INTEGER, in_transit INTEGER)"))
    monkeypatch.setattr("app.main.engine", eng)
    ensure_schema()
    cols = {c["name"] for c in inspect(eng).get_columns("lanes")}
    assert "min_face" in cols
    ensure_schema()  # 幂等
