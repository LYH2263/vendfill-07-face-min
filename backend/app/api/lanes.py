import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Lane, RefillOrder
from app.services.fill_engine import build_fill_lines, compute_gap, summarize
router = APIRouter(prefix="/lanes", tags=["lanes"])

def lane_payload(r: Lane) -> dict:
    gap = compute_gap(r.capacity, r.stock, r.in_transit, r.min_face)
    return {"id": r.id, "location_id": r.location_id, "slot_no": r.slot_no, "sku_name": r.sku_name,
            "capacity": r.capacity, "stock": r.stock, "in_transit": r.in_transit,
            "min_face": r.min_face, "gap": gap,
            "fill_pct": round(r.stock / r.capacity * 100, 1) if r.capacity else 0}

@router.get("")
def list_lanes(location_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Lane).order_by(Lane.slot_no)
    if location_id is not None: q = q.where(Lane.location_id == location_id)
    return [lane_payload(r) for r in db.scalars(q).all()]

class MinFaceUpdate(BaseModel):
    min_face: int | None = None  # 留空或 0 = 与现网相同

@router.patch("/{lane_id}")
def update_min_face(lane_id: int, body: MinFaceUpdate, db: Session = Depends(get_db)):
    lane = db.get(Lane, lane_id)
    if not lane: raise HTTPException(404, "货道不存在")
    face = body.min_face or 0
    if face < 0: raise HTTPException(400, "陈列面不能为负")
    if face > lane.capacity: raise HTTPException(400, "陈列面不能大于容量")  # 三处不动
    lane.min_face = face
    # 若有最新补货单：同一事务按新有效缺口重写该单；历史非最新单不回刷
    order = db.scalars(select(RefillOrder).where(RefillOrder.location_id == lane.location_id)
                       .order_by(RefillOrder.id.desc())).first()
    if order:
        lanes = db.scalars(select(Lane).where(Lane.location_id == lane.location_id)
                           .order_by(Lane.slot_no)).all()
        payload = [{"id": l.id, "slot_no": l.slot_no, "sku_name": l.sku_name,
                    "capacity": l.capacity, "stock": l.stock, "in_transit": l.in_transit,
                    "min_face": l.min_face} for l in lanes]
        order.lines_json = json.dumps(summarize(build_fill_lines(payload)), ensure_ascii=False)
    try:
        db.commit()
    except Exception:
        db.rollback()  # 失败则陈列面与单全回改前
        raise HTTPException(500, "保存失败，已回滚")
    return {**lane_payload(lane), "order_id": order.id if order else None}
