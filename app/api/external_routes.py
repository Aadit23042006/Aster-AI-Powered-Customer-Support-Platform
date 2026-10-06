
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.db.models import Product
from app.phase4 import validate_api_key

router=APIRouter(prefix="/api/v1/external",tags=["public-api"])

def api_key_dep(x_api_key:str|None=Header(default=None,alias="X-API-Key"),db:Session=Depends(get_db)):
    return validate_api_key(db,x_api_key or "", "products:read")

@router.get("/products")
def products(q:str|None=None, key=Depends(api_key_dep), db:Session=Depends(get_db)):
    query=db.query(Product).filter(Product.organization_id==key.organization_id,Product.active.is_(True))
    if q: query=query.filter((Product.name.ilike(f"%{q}%")) | (Product.sku.ilike(f"%{q}%")))
    return [{
        "id": str(x.id), "sku": x.sku, "name": x.name,
        "description": x.description, "category": x.category,
        "price": float(x.price), "currency": x.currency,
        "inventory_status": x.inventory_status,
        "attributes": x.attributes, "image_url": x.image_url,
        "active": x.active,
    } for x in query.limit(100).all()]

@router.get("/recommendations")
def recommendations(q:str, key=Depends(api_key_dep)):
    # Kept explicit rather than exposing internal recommendation state through
    # an unscoped route. Integrators should use the authenticated endpoint
    # until a dedicated end-user identity mapping is configured.
    return {"query":q,"products":[],"detail":"Use /api/v1/recommendations with a user session; no anonymous customer data is exposed."}
