import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models.models import Lane, Location, RefillOrder


@pytest.fixture()
def client(engine):
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    loc = Location(code="VM-01", name="测试点位", address="")
    db.add(loc); db.flush()
    seed_lanes = [
        ("A1", "矿泉水", 20, 5, 0),
        ("A2", "可乐", 18, 18, 0),
        ("B2", "巧克力", 15, 10, 5),
    ]
    a1_id = None
    for slot, sku, cap, stock, transit in seed_lanes:
        lane = Lane(location_id=loc.id, slot_no=slot, sku_name=sku,
                    capacity=cap, stock=stock, in_transit=transit, min_facing=0)
        db.add(lane); db.flush()
        if slot == "A1":
            a1_id = lane.id
    db.commit(); db.close()

    def override_get_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c, TestSession, a1_id
    app.dependency_overrides.clear()


def line_by_slot(order_json, slot):
    return next(l for l in json.loads(order_json)["lines"] if l["slot_no"] == slot)


def test_put_facing_rewrites_latest_and_three_places_match(client):
    c, _Session, a1_id = client
    run = c.post("/api/refills/run?location_id=1")
    assert run.status_code == 200
    before = run.json()
    a1_before = next(l for l in before["lines"] if l["slot_no"] == "A1")
    assert a1_before["gap"] == 15 and a1_before["fill_qty"] == 15

    res = c.put(f"/api/lanes/{a1_id}", json={"min_facing": 8})
    assert res.status_code == 200
    assert res.json()["lane"]["gap"] == 18

    lanes = {r["slot_no"]: r for r in c.get("/api/lanes?location_id=1").json()}
    latest = c.get("/api/refills/latest?location_id=1").json()
    summary = c.get("/api/refills/summary?location_id=1").json()
    a1_latest = next(l for l in latest["lines"] if l["slot_no"] == "A1")

    # 货道页有效缺口与最新单一致，且高于只按库存 5 的口径 15
    assert lanes["A1"]["gap"] == 18
    assert a1_latest["gap"] == 18 and a1_latest["fill_qty"] == 18
    assert lanes["A1"]["status"] == a1_latest["status"] == "need_fill"
    # 汇总与最新单同数
    assert summary["total_fill"] == latest["total_fill"]
    assert summary["need_fill_count"] == latest["need_fill_count"]
    # 最新单是同一条记录（就地重写，未新建）
    assert latest["id"] == before["id"]
    # 因陈列面抬高出现正补量的 A1 不进满仓
    full_slots = {l["slot_no"] for l in c.get("/api/refills/full?location_id=1").json()["lanes"]}
    assert "A1" not in full_slots and "A2" in full_slots


def test_facing_over_capacity_rejected_three_places_untouched(client):
    c, _Session, a1_id = client
    c.post("/api/refills/run?location_id=1")
    res = c.put(f"/api/lanes/{a1_id}", json={"min_facing": 21})
    assert res.status_code == 422

    lanes = {r["slot_no"]: r for r in c.get("/api/lanes?location_id=1").json()}
    latest = c.get("/api/refills/latest?location_id=1").json()
    summary = c.get("/api/refills/summary?location_id=1").json()
    assert lanes["A1"]["min_facing"] == 0 and lanes["A1"]["gap"] == 15
    a1 = next(l for l in latest["lines"] if l["slot_no"] == "A1")
    assert a1["gap"] == 15 and a1["fill_qty"] == 15
    assert summary["total_fill"] == latest["total_fill"]


def test_historical_orders_not_refreshed(client):
    c, Session, a1_id = client
    first = c.post("/api/refills/run?location_id=1").json()
    second = c.post("/api/refills/run?location_id=1").json()
    assert second["id"] > first["id"]

    res = c.put(f"/api/lanes/{a1_id}", json={"min_facing": 8})
    assert res.status_code == 200

    db = Session()
    old = db.get(RefillOrder, first["id"])
    newest = db.get(RefillOrder, second["id"])
    # 历史单保持改前快照，最新单按新有效缺口重写
    assert line_by_slot(old.lines_json, "A1")["gap"] == 15
    assert line_by_slot(newest.lines_json, "A1")["gap"] == 18
    db.close()


def test_blank_or_zero_facing_equals_current_net(client):
    c, _Session, a1_id = client
    c.post("/api/refills/run?location_id=1")
    assert c.put(f"/api/lanes/{a1_id}", json={"min_facing": 0}).json()["lane"]["gap"] == 15
    latest = c.get("/api/refills/latest?location_id=1").json()
    assert next(l for l in latest["lines"] if l["slot_no"] == "A1")["gap"] == 15


def test_put_facing_without_any_order_still_saves(client):
    c, _Session, a1_id = client
    res = c.put(f"/api/lanes/{a1_id}", json={"min_facing": 8})
    assert res.status_code == 200
    assert res.json()["latest"] is None
    lanes = {r["slot_no"]: r for r in c.get("/api/lanes?location_id=1").json()}
    assert lanes["A1"]["min_facing"] == 8 and lanes["A1"]["gap"] == 18
