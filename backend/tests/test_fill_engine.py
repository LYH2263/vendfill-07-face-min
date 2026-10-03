from app.services.fill_engine import build_fill_lines, compute_gap, summarize

def test_gap_basic():
    assert compute_gap(20, 5, 0) == 15
    assert compute_gap(20, 10, 5) == 5

def test_no_negative_fill():
    lanes = [{"id": 1, "slot_no": "A1", "sku_name": "水", "capacity": 10, "stock": 12, "in_transit": 0}]
    lines = build_fill_lines(lanes)
    assert lines[0].fill_qty == 0
    assert lines[0].status == "overbooked"

def test_cap_by_gap():
    lanes = [{"id": 1, "slot_no": "A1", "sku_name": "水", "capacity": 20, "stock": 5, "in_transit": 0}]
    lines = build_fill_lines(lanes, requested={1: 100})
    assert lines[0].fill_qty == 15
    assert lines[0].gap == 15

def test_full_zero_fill():
    lanes = [{"id": 1, "slot_no": "A1", "sku_name": "水", "capacity": 10, "stock": 8, "in_transit": 2}]
    s = summarize(build_fill_lines(lanes))
    assert s["full_count"] == 1
    assert s["total_fill"] == 0

# ---- 最低陈列面 ----

def test_face_blank_or_zero_same_as_current():
    # 陈列面留空或 0 与现网相同
    assert compute_gap(20, 5, 0, 0) == 15
    assert compute_gap(20, 5, 0) == 15
    lanes = [{"id": 1, "slot_no": "A1", "sku_name": "水", "capacity": 20, "stock": 5,
              "in_transit": 0, "min_face": None}]
    assert build_fill_lines(lanes)[0].gap == 15

def test_face_elevates_gap_when_stock_below():
    # 库存 5 低于陈列面 8：有效缺口 = 现网 15 + 欠账 3 = 18，高于只按库存 5 的口径
    assert compute_gap(20, 5, 0, 8) == 18
    lanes = [{"id": 1, "slot_no": "A1", "sku_name": "水", "capacity": 20, "stock": 5,
              "in_transit": 0, "min_face": 8}]
    line = build_fill_lines(lanes)[0]
    assert line.gap == 18 and line.fill_qty == 18 and line.status == "need_fill"

def test_face_at_or_above_stock_falls_back():
    # 库存已达陈列面及以上时退回现网缺口
    assert compute_gap(20, 10, 0, 8) == 10
    assert compute_gap(20, 8, 0, 8) == 12

def test_face_fill_capped_by_capacity():
    # 补量仍不得超过容量约束
    lanes = [{"id": 1, "slot_no": "A1", "sku_name": "水", "capacity": 10, "stock": 1,
              "in_transit": 0, "min_face": 9}]
    line = build_fill_lines(lanes)[0]
    assert line.gap == 17
    assert line.fill_qty == 10

def test_face_never_negative_fill():
    # 在途超占时有效缺口仍不得为负地参与补量
    lanes = [{"id": 1, "slot_no": "A1", "sku_name": "水", "capacity": 20, "stock": 5,
              "in_transit": 30, "min_face": 8}]
    line = build_fill_lines(lanes)[0]
    assert line.gap == -12  # 现网 −15 抬 3 后仍为负
    assert line.fill_qty == 0
    assert line.status == "overbooked"

def test_face_elevated_lane_not_full():
    # 现网缺口为 0 的道被陈列面抬出正补量：待补与满仓互斥
    lanes = [{"id": 1, "slot_no": "B2", "sku_name": "巧克力", "capacity": 15, "stock": 10,
              "in_transit": 5, "min_face": 12}]
    s = summarize(build_fill_lines(lanes))
    line = s["lines"][0]
    assert line["gap"] == 2 and line["fill_qty"] == 2
    assert line["status"] == "need_fill"
    assert s["full_count"] == 0 and s["need_fill_count"] == 1
