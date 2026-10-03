"""Vending refill: gap = capacity - stock - in_transit; fills capped by gap; no negative fills.

最低陈列面（min_face）：货道可登记最低陈列面件数。库存低于陈列面时，有效缺口在
「容量−陈列面−在途」与「容量−库存−在途」的较大者（该分支下恒为后者，即现网缺口）
之上再抬高陈列面欠账（陈列面−库存）；库存达到陈列面及以上、或陈列面为空/0 时退回
现网缺口。有效缺口不得为负地参与补量，补量仍不得超过容量约束。
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
    min_face: int
    gap: int
    fill_qty: int
    status: str  # need_fill | full | overbooked

def compute_gap(capacity: int, stock: int, in_transit: int, min_face: int = 0) -> int:
    """有效缺口。库存低于陈列面时按陈列面抬高：现网缺口 +（陈列面−库存）。"""
    gap = capacity - stock - in_transit
    if min_face > 0 and stock < min_face:
        gap += min_face - stock
    return gap

def build_fill_lines(lanes: list[dict], requested: dict[int, int] | None = None) -> list[FillLine]:
    """requested optional desired fill per lane_id; capped by gap and capacity; never negative."""
    lines: list[FillLine] = []
    for lane in lanes:
        capacity = int(lane["capacity"])
        min_face = int(lane.get("min_face") or 0)
        gap = compute_gap(capacity, int(lane["stock"]), int(lane["in_transit"]), min_face)
        if gap < 0:
            status = "overbooked"
            fill = 0
        elif gap == 0:
            status = "full"
            fill = 0
        else:
            status = "need_fill"
            desire = gap if requested is None else int(requested.get(lane["id"], gap))
            fill = max(0, min(desire, gap, capacity))
        lines.append(FillLine(
            lane_id=lane["id"], slot_no=lane["slot_no"], sku_name=lane["sku_name"],
            capacity=capacity, stock=lane["stock"], in_transit=lane["in_transit"],
            min_face=min_face, gap=gap, fill_qty=fill, status=status,
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
