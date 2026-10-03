from app.services.fill_engine import build_fill_lines, compute_gap, summarize

def lane(**kw):
    base = {"id": 1, "slot_no": "A1", "sku_name": "水", "capacity": 20,
            "stock": 5, "in_transit": 0, "min_facing": 0}
    base.update(kw)
    return base

def test_gap_basic():
    assert compute_gap(20, 5, 0) == 15
    assert compute_gap(20, 10, 5) == 5

def test_no_negative_fill():
    lines = build_fill_lines([lane(capacity=10, stock=12)])
    assert lines[0].fill_qty == 0
    assert lines[0].status == "overbooked"

def test_cap_by_gap():
    lines = build_fill_lines([lane()], requested={1: 100})
    assert lines[0].fill_qty == 15
    assert lines[0].gap == 15

def test_full_zero_fill():
    s = summarize(build_fill_lines([lane(capacity=10, stock=8, in_transit=2)]))
    assert s["full_count"] == 1
    assert s["total_fill"] == 0

def test_min_facing_raises_fill_above_stock_only_gap():
    # 种子 A1：容量20 库存5 陈列面8 -> 15 + (8-5) = 18，高于只按库存口径的 15
    assert compute_gap(20, 5, 0, 8) == 18
    lines = build_fill_lines([lane(min_facing=8)])
    assert lines[0].gap == 18
    assert lines[0].fill_qty == 18
    assert lines[0].status == "need_fill"

def test_blank_or_zero_facing_equals_current_net():
    assert compute_gap(20, 5, 0, 0) == 15
    lines = build_fill_lines([lane(min_facing=0)])
    assert lines[0].fill_qty == 15

def test_stock_at_or_above_facing_falls_back_to_current_net():
    # 库存已达陈列面：退回现网缺口 20-10=10，不叠加兜底
    assert compute_gap(20, 10, 0, 8) == 10
    # 库存恰等于陈列面
    assert compute_gap(20, 8, 0, 8) == 12

def test_in_transit_covers_facing_gap():
    # 在途 10 已覆盖陈列面（5+10>=8），只剩余现网缺口 5
    assert compute_gap(20, 5, 10, 8) == 5

def test_gap_never_negative_and_fill_never_above_capacity():
    # 兜底后理论 20+20=40，夹到容量 20
    assert compute_gap(20, 0, 0, 20) == 20
    lines = build_fill_lines([lane(stock=0, min_facing=20)])
    assert lines[0].fill_qty == 20
    assert lines[0].status == "need_fill"
    # 超占仍不为负
    assert compute_gap(10, 12, 0, 8) == 0

def test_facing_fill_not_marked_full():
    # 现网缺口为 0 但陈列面未满足：待补，与满仓互斥
    lines = build_fill_lines([lane(capacity=10, stock=8, in_transit=0, min_facing=10)])
    assert lines[0].gap == 4
    assert lines[0].status == "need_fill"
    s = summarize(lines)
    assert s["need_fill_count"] == 1 and s["full_count"] == 0

def test_requested_capped_by_effective_gap():
    lines = build_fill_lines([lane(min_facing=8)], requested={1: 100})
    assert lines[0].fill_qty == 18
