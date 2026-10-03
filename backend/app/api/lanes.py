import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Lane, RefillOrder
from app.services.fill_engine import build_fill_lines, compute_gap, summarize
router = APIRouter(prefix="/lanes", tags=["lanes"])

class LaneUpdate(BaseModel):
    # 最低陈列面件数；None 或 0 表示不启用，与现网口径一致
    min_facing: int | None = None

def lane_dict(r: Lane) -> dict:
    gap = compute_gap(r.capacity, r.stock, r.in_transit, r.min_facing or 0)
    base = r.capacity - r.stock - r.in_transit
    if base < 0:
        status = "overbooked"
    elif gap == 0:
        status = "full"
    else:
        status = "need_fill"
    return {"id": r.id, "location_id": r.location_id, "slot_no": r.slot_no, "sku_name": r.sku_name,
            "capacity": r.capacity, "stock": r.stock, "in_transit": r.in_transit,
            "min_facing": r.min_facing or 0, "gap": gap, "status": status,
            "fill_pct": round(r.stock / r.capacity * 100, 1) if r.capacity else 0}

@router.get("")
def list_lanes(location_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Lane).order_by(Lane.slot_no)
    if location_id is not None: q = q.where(Lane.location_id == location_id)
    return [lane_dict(r) for r in db.scalars(q).all()]

@router.put("/{lane_id}")
def update_lane(lane_id: int, body: LaneUpdate, db: Session = Depends(get_db)):
    lane = db.get(Lane, lane_id)
    if not lane:
        raise HTTPException(404, "货道不存在")
    facing = body.min_facing or 0
    if facing < 0:
        raise HTTPException(422, "最低陈列面不能为负")
    if facing > lane.capacity:
        # 陈列面大于容量：拒绝保存，货道、最新单、汇总三处不动
        raise HTTPException(422, "最低陈列面不得大于货道容量")
    try:
        lane.min_facing = facing
        db.flush()  # 同事务内让重算读到新陈列面
        order = db.scalars(select(RefillOrder).where(RefillOrder.location_id == lane.location_id)
                           .order_by(RefillOrder.id.desc())).first()
        latest = None
        if order is not None:
            # 有最新补货单：同提交按新有效缺口就地重写该单（历史单不回刷）
            lanes = db.scalars(select(Lane).where(Lane.location_id == lane.location_id)
                               .order_by(Lane.slot_no)).all()
            payload = [{"id": l.id, "slot_no": l.slot_no, "sku_name": l.sku_name,
                        "capacity": l.capacity, "stock": l.stock, "in_transit": l.in_transit,
                        "min_facing": l.min_facing or 0} for l in lanes]
            summary = summarize(build_fill_lines(payload))
            order.lines_json = json.dumps(summary, ensure_ascii=False)
            db.flush()
            latest = {"id": order.id, "location_id": order.location_id, **summary}
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        # 失败则陈列面与单全回改前
        db.rollback()
        raise HTTPException(500, "保存失败，陈列面与补货单已回滚")
    db.refresh(lane)
    return {"lane": lane_dict(lane), "latest": latest}
