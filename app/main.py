from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from typing import List, Optional
from celery.result import AsyncResult
import httpx

from app.database import get_db, engine
from app import models, schemas
from app.tasks import import_products_task, trigger_webhooks
from app.celery_app import celery_app

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Product Importer API")

# HTML Frontend
@app.get("/", response_class=HTMLResponse)
async def root():
    with open("app/static/index.html", "r", encoding="utf-8") as f:
        return f.read()

# ============= PRODUCT ENDPOINTS =============

@app.post("/api/products/upload", response_model=schemas.UploadResponse)
async def upload_products(file: UploadFile = File(...)):
    """
    Upload CSV file for product import (async processing).
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    try:
        content = await file.read()
        csv_content = content.decode('utf-8')
        
        # Start async task
        task = import_products_task.delay(csv_content)
        
        return schemas.UploadResponse(
            task_id=task.id,
            message="Upload started. Check status using task_id."
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

@app.get("/api/tasks/{task_id}", response_model=schemas.TaskStatus)
async def get_task_status(task_id: str):
    """
    Get status of an async task (e.g., CSV import).
    """
    task = AsyncResult(task_id, app=celery_app)
    
    if task.state == 'PENDING':
        response = {
            'task_id': task_id,
            'status': 'pending',
            'message': 'Task is waiting to be processed'
        }
    elif task.state == 'PROGRESS':
        response = {
            'task_id': task_id,
            'status': 'processing',
            'progress': task.info.get('progress', 0),
            'total': task.info.get('total', 0),
            'message': task.info.get('message', 'Processing...')
        }
    elif task.state == 'SUCCESS':
        response = {
            'task_id': task_id,
            'status': 'completed',
            'progress': task.info.get('total', 0),
            'total': task.info.get('total', 0),
            'message': task.info.get('message', 'Import completed successfully')
        }
    elif task.state == 'FAILURE':
        response = {
            'task_id': task_id,
            'status': 'failed',
            'message': str(task.info)
        }
    else:
        response = {
            'task_id': task_id,
            'status': task.state.lower(),
            'message': str(task.info)
        }
    
    return response

@app.get("/api/products", response_model=List[schemas.Product])
def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """
    List products with pagination and filtering.
    """
    query = db.query(models.Product)
    
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                models.Product.sku.ilike(search_filter),
                models.Product.name.ilike(search_filter),
                models.Product.description.ilike(search_filter)
            )
        )
    
    if is_active is not None:
        query = query.filter(models.Product.is_active == is_active)
    
    query = query.order_by(models.Product.id.desc())
    products = query.offset(skip).limit(limit).all()
    
    return products

@app.get("/api/products/count")
def count_products(
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """
    Get total count of products (for pagination).
    """
    query = db.query(func.count(models.Product.id))
    
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                models.Product.sku.ilike(search_filter),
                models.Product.name.ilike(search_filter),
                models.Product.description.ilike(search_filter)
            )
        )
    
    if is_active is not None:
        query = query.filter(models.Product.is_active == is_active)
    
    count = query.scalar()
    return {"count": count}

@app.post("/api/products", response_model=schemas.Product)
def create_product(product: schemas.ProductCreate, db: Session = Depends(get_db)):
    """
    Create a new product.
    """
    # Check if SKU already exists (case-insensitive)
    existing = db.query(models.Product).filter(
        func.lower(models.Product.sku) == product.sku.lower()
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="SKU already exists")
    
    db_product = models.Product(**product.dict())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    
    # Trigger webhooks
    trigger_webhooks.delay('product.created', {'sku': db_product.sku})
    
    return db_product

@app.get("/api/products/{product_id}", response_model=schemas.Product)
def get_product(product_id: int, db: Session = Depends(get_db)):
    """
    Get a specific product by ID.
    """
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@app.put("/api/products/{product_id}", response_model=schemas.Product)
def update_product(
    product_id: int,
    product_update: schemas.ProductUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a product.
    """
    db_product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    update_data = product_update.dict(exclude_unset=True)
    
    # Check SKU uniqueness if being updated
    if 'sku' in update_data and update_data['sku'] != db_product.sku:
        existing = db.query(models.Product).filter(
            func.lower(models.Product.sku) == update_data['sku'].lower()
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="SKU already exists")
    
    for key, value in update_data.items():
        setattr(db_product, key, value)
    
    db.commit()
    db.refresh(db_product)
    
    # Trigger webhooks
    trigger_webhooks.delay('product.updated', {'sku': db_product.sku})
    
    return db_product

@app.delete("/api/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    """
    Delete a product.
    """
    db_product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    sku = db_product.sku
    db.delete(db_product)
    db.commit()
    
    # Trigger webhooks
    trigger_webhooks.delay('product.deleted', {'sku': sku})
    
    return {"message": "Product deleted successfully"}

@app.delete("/api/products")
def delete_all_products(db: Session = Depends(get_db)):
    """
    Delete all products (bulk delete).
    """
    count = db.query(models.Product).count()
    db.query(models.Product).delete()
    db.commit()
    
    # Trigger webhooks
    trigger_webhooks.delay('product.bulk_deleted', {'count': count})
    
    return {"message": f"Successfully deleted {count} products"}

# ============= WEBHOOK ENDPOINTS =============

@app.get("/api/webhooks", response_model=List[schemas.Webhook])
def list_webhooks(db: Session = Depends(get_db)):
    """
    List all webhooks.
    """
    webhooks = db.query(models.Webhook).all()
    return webhooks

@app.post("/api/webhooks", response_model=schemas.Webhook)
def create_webhook(webhook: schemas.WebhookCreate, db: Session = Depends(get_db)):
    """
    Create a new webhook.
    """
    db_webhook = models.Webhook(**webhook.dict())
    db.add(db_webhook)
    db.commit()
    db.refresh(db_webhook)
    return db_webhook

@app.put("/api/webhooks/{webhook_id}", response_model=schemas.Webhook)
def update_webhook(
    webhook_id: int,
    webhook_update: schemas.WebhookUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a webhook.
    """
    db_webhook = db.query(models.Webhook).filter(models.Webhook.id == webhook_id).first()
    if not db_webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    update_data = webhook_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_webhook, key, value)
    
    db.commit()
    db.refresh(db_webhook)
    return db_webhook

@app.delete("/api/webhooks/{webhook_id}")
def delete_webhook(webhook_id: int, db: Session = Depends(get_db)):
    """
    Delete a webhook.
    """
    db_webhook = db.query(models.Webhook).filter(models.Webhook.id == webhook_id).first()
    if not db_webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    db.delete(db_webhook)
    db.commit()
    return {"message": "Webhook deleted successfully"}

@app.post("/api/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: int, db: Session = Depends(get_db)):
    """
    Test a webhook by sending a test payload.
    """
    db_webhook = db.query(models.Webhook).filter(models.Webhook.id == webhook_id).first()
    if not db_webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            import time
            start = time.time()
            
            response = await client.post(
                db_webhook.url,
                json={
                    'event': 'webhook.test',
                    'data': {'test': True, 'webhook_id': webhook_id}
                },
                headers={'Content-Type': 'application/json'}
            )
            
            elapsed = int((time.time() - start) * 1000)
            
            return {
                'success': True,
                'status_code': response.status_code,
                'response_time_ms': elapsed,
                'message': f'Webhook responded with status {response.status_code}'
            }
    except Exception as e:
        return {
            'success': False,
            'message': f'Webhook test failed: {str(e)}'
        }

@app.get("/health")
def health_check():
    """
    Health check endpoint.
    """
    return {"status": "healthy"}