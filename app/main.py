from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

from fastapi import FastAPI, File, UploadFile, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional

from app.database import engine, get_db, Base
from app.models import Product, Webhook
from app.schemas import (
    Product as ProductSchema,
    ProductCreate,
    ProductUpdate,
    Webhook as WebhookSchema,
    WebhookCreate
)
from app.tasks import process_csv_upload, trigger_webhooks

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Product Importer API")

# Serve static files
@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("app/static/index.html", "r", encoding="utf-8") as f:
        return f.read()

# API Endpoints

@app.post("/api/upload")
async def upload_csv(file: UploadFile = File(...)):
    """Upload CSV file for processing"""
    try:
        content = await file.read()
        csv_content = content.decode('utf-8')
        
        # Process CSV synchronously
        result = process_csv_upload(csv_content)
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/products")
async def get_products(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sku: Optional[str] = None,
    name: Optional[str] = None,
    active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """Get products with filtering and pagination"""
    query = db.query(Product)
    
    if sku:
        query = query.filter(Product.sku.ilike(f'%{sku}%'))
    if name:
        query = query.filter(Product.name.ilike(f'%{name}%'))
    if active is not None:
        query = query.filter(Product.is_active == active)
    
    total = query.count()
    products = query.offset((page - 1) * limit).limit(limit).all()
    
    return {
        "products": products,
        "total": total,
        "page": page,
        "limit": limit
    }

# IMPORTANT: bulk-delete MUST come BEFORE {product_id} routes
@app.delete("/api/products/bulk-delete")
async def bulk_delete_products(db: Session = Depends(get_db)):
    """Delete all products"""
    count = db.query(Product).count()
    db.query(Product).delete(synchronize_session=False)
    db.commit()
    
    return {"message": f"Deleted {count} products"}

@app.get("/api/products/{product_id}", response_model=ProductSchema)
async def get_product(product_id: int, db: Session = Depends(get_db)):
    """Get single product"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@app.post("/api/products", response_model=ProductSchema)
async def create_product(
    product: ProductCreate, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Create new product"""
    existing = db.query(Product).filter(
        func.lower(Product.sku) == func.lower(product.sku)
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="SKU already exists")
    
    db_product = Product(**product.dict())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    
    # Trigger webhooks in background
    background_tasks.add_task(trigger_webhooks, 'product.created', {'sku': db_product.sku})
    
    return db_product

@app.put("/api/products/{product_id}", response_model=ProductSchema)
async def update_product(
    product_id: int,
    product: ProductUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Update product"""
    db_product = db.query(Product).filter(Product.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    if product.sku.lower() != db_product.sku.lower():
        existing = db.query(Product).filter(
            func.lower(Product.sku) == func.lower(product.sku),
            Product.id != product_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="SKU already exists")
    
    for key, value in product.dict().items():
        setattr(db_product, key, value)
    
    db.commit()
    db.refresh(db_product)
    
    # Trigger webhooks in background
    background_tasks.add_task(trigger_webhooks, 'product.updated', {'sku': db_product.sku})
    
    return db_product

@app.delete("/api/products/{product_id}")
async def delete_product(
    product_id: int, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Delete product"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    sku = product.sku
    db.delete(product)
    db.commit()
    
    # Trigger webhooks in background
    background_tasks.add_task(trigger_webhooks, 'product.deleted', {'sku': sku})
    
    return {"message": "Product deleted"}

# Webhook Endpoints

@app.get("/api/webhooks", response_model=List[WebhookSchema])
async def get_webhooks(db: Session = Depends(get_db)):
    """Get all webhooks"""
    return db.query(Webhook).all()

@app.post("/api/webhooks", response_model=WebhookSchema)
async def create_webhook(webhook: WebhookCreate, db: Session = Depends(get_db)):
    """Create webhook"""
    db_webhook = Webhook(**webhook.dict())
    db.add(db_webhook)
    db.commit()
    db.refresh(db_webhook)
    return db_webhook

@app.delete("/api/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: int, db: Session = Depends(get_db)):
    """Delete webhook"""
    webhook = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    db.delete(webhook)
    db.commit()
    return {"message": "Webhook deleted"}

@app.post("/api/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: int, db: Session = Depends(get_db)):
    """Test webhook"""
    webhook = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    try:
        import httpx
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                webhook.url,
                json={'event': 'test', 'data': {'message': 'Test webhook'}}
            )
            return {
                "message": f"Webhook tested. Status: {response.status_code}",
                "status_code": response.status_code
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Webhook test failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
