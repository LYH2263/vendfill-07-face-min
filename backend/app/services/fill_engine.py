"""Vending refill engine.

现网缺口 base = capacity - stock - in_transit。
设置最低陈列面 min_facing（>0）且库存低于陈列面时，有效缺口在现网缺口之上
再补足陈列面兜底量 max(0, min_facing - stock - in_transit)，并夹在 [0, capacity]：
有效缺口永远不为负，补量永远不超过容量约束。库存已达陈列面（或陈列面留空/0）
时退回现网缺口。
"""
from __future__ import annotations
from dataclasses import asdict, dataclass

@dataclass
class FillLine:
    lane_id: int
    slot_no: str
    sku_name: str
    capacity: int
    stock: int
    in_transit: int
    min_facing: int
    gap: int
    fill_qty: int
    status: str  # need_fill | full | overbooked

def compute_gap(capacity: int, stock: int, in_transit: int, min_facing: int = 0) -> int:
    """有效缺口（夹到 0..容量）。min_facing 留空或 0 时与现网口径一致。"""
    capacity, stock, in_transit = int(capacity), int(stock), int(in_transit)
    facing = int(min_facing or 0)
    base = capacity - stock - in_transit
    if facing > 0 and stock < facing:
        effective = base + max(0, facing - stock - in_transit)
    else:
        effective = base
    return max(0, min(capacity, effective))

def build_fill_lines(lanes: list[dict], requested: dict[int, int] | None = None) -> list[FillLine]:
    """requested optional desired fill per lane_id; capped by effective gap; never negative."""
    lines: list[FillLine] = []
    for lane in lanes:
        capacity, stock, in_transit = int(lane["capacity"]), int(lane["stock"]), int(lane["in_transit"])
        facing = int(lane.get("min_facing") or 0)
        base = capacity - stock - in_transit
        gap = compute_gap(capacity, stock, in_transit, facing)
        if base < 0:
            status = "overbooked"
            fill = 0
        elif gap == 0:
            status = "full"
            fill = 0
        else:
            status = "need_fill"
            desire = gap if requested is None else int(requested.get(lane["id"], gap))
            fill = max(0, min(desire, gap))
        lines.append(FillLine(
            lane_id=lane["id"], slot_no=lane["slot_no"], sku_name=lane["sku_name"],
            capacity=capacity, stock=stock, in_transit=in_transit, min_facing=facing,
            gap=gap, fill_qty=fill, status=status,
        ))
    return lines

def summarize(lines: list[FillLine]) -> dict:
    return {
        "total_fill": sum(l.fill_qty for l in lines),
        "need_fill_count": sum(1 for l in lines if l.status == "need_fill"),
        "full_count": sum(1 for l in lines if l.status == "full"),
        "overbooked_count": sum(1 for l in lines if l.status == "overbooked"),
        "lines": [asdict(l) for l in lines],
    }
