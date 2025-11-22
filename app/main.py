from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

from fastapi import FastAPI, File, UploadFile, Depends, HTTPException, Query
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
from app.celery_app import celery_app

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Product Importer API")

# Serve static files
@app.get("/", response_class=HTMLResponse)
async def read_root():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Product Importer</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h1 { color: #333; margin-bottom: 30px; }
        .section { margin-bottom: 40px; }
        h2 { color: #666; margin-bottom: 20px; font-size: 20px; border-bottom: 2px solid #007bff; padding-bottom: 10px; }
        .upload-area { border: 2px dashed #ccc; padding: 40px; text-align: center; border-radius: 8px; margin-bottom: 20px; }
        .upload-area:hover { border-color: #007bff; background: #f9f9f9; }
        input[type="file"] { display: none; }
        button { background: #007bff; color: white; padding: 12px 24px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; margin: 5px; }
        button:hover { background: #0056b3; }
        button.danger { background: #dc3545; }
        button.danger:hover { background: #c82333; }
        button.secondary { background: #6c757d; }
        button.secondary:hover { background: #545b62; }
        .progress-bar { width: 100%; height: 30px; background: #e0e0e0; border-radius: 15px; overflow: hidden; margin: 20px 0; }
        .progress-fill { height: 100%; background: #007bff; transition: width 0.3s; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #f8f9fa; font-weight: bold; color: #333; }
        tr:hover { background: #f8f9fa; }
        .filters { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
        input[type="text"], select { padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; }
        .pagination { display: flex; gap: 10px; justify-content: center; margin-top: 20px; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; }
        .modal-content { background: white; margin: 100px auto; padding: 30px; width: 90%; max-width: 500px; border-radius: 8px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; color: #333; }
        .status { padding: 10px; border-radius: 4px; margin: 10px 0; }
        .status.success { background: #d4edda; color: #155724; }
        .status.error { background: #f8d7da; color: #721c24; }
        .status.info { background: #d1ecf1; color: #0c5460; }
        .actions { display: flex; gap: 5px; }
        .btn-sm { padding: 6px 12px; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🛒 Product Importer</h1>
        
        <!-- Upload Section -->
        <div class="section">
            <h2>📤 Upload CSV File</h2>
            <div class="upload-area" onclick="document.getElementById('fileInput').click()">
                <p>Click to select CSV file (up to 500,000 products)</p>
                <input type="file" id="fileInput" accept=".csv" onchange="uploadFile()">
            </div>
            <div id="uploadStatus"></div>
            <div class="progress-bar" id="progressBar" style="display:none;">
                <div class="progress-fill" id="progressFill">0%</div>
            </div>
        </div>

        <!-- Product Management Section -->
        <div class="section">
            <h2>📦 Product Management</h2>
            <div class="filters">
                <input type="text" id="searchSku" placeholder="Search by SKU" onkeyup="loadProducts()">
                <input type="text" id="searchName" placeholder="Search by Name" onkeyup="loadProducts()">
                <select id="filterActive" onchange="loadProducts()">
                    <option value="">All Status</option>
                    <option value="true">Active</option>
                    <option value="false">Inactive</option>
                </select>
                <button onclick="openAddModal()">+ Add Product</button>
                <button class="danger" onclick="confirmBulkDelete()">Delete All Products</button>
            </div>
            <table id="productsTable">
                <thead>
                    <tr>
                        <th>SKU</th>
                        <th>Name</th>
                        <th>Description</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="productsBody"></tbody>
            </table>
            <div class="pagination" id="pagination"></div>
        </div>

        <!-- Webhook Management Section -->
        <div class="section">
            <h2>🔗 Webhook Management</h2>
            <button onclick="openWebhookModal()">+ Add Webhook</button>
            <table id="webhooksTable">
                <thead>
                    <tr>
                        <th>URL</th>
                        <th>Event Type</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="webhooksBody"></tbody>
            </table>
        </div>
    </div>

    <!-- Product Modal -->
    <div id="productModal" class="modal">
        <div class="modal-content">
            <h2 id="modalTitle">Add Product</h2>
            <form id="productForm" onsubmit="saveProduct(event)">
                <div class="form-group">
                    <label>SKU *</label>
                    <input type="text" id="productSku" required>
                </div>
                <div class="form-group">
                    <label>Name *</label>
                    <input type="text" id="productName" required>
                </div>
                <div class="form-group">
                    <label>Description</label>
                    <input type="text" id="productDescription">
                </div>
                <div class="form-group">
                    <label>
                        <input type="checkbox" id="productActive" checked> Active
                    </label>
                </div>
                <button type="submit">Save</button>
                <button type="button" class="secondary" onclick="closeModal('productModal')">Cancel</button>
            </form>
        </div>
    </div>

    <!-- Webhook Modal -->
    <div id="webhookModal" class="modal">
        <div class="modal-content">
            <h2>Add Webhook</h2>
            <form id="webhookForm" onsubmit="saveWebhook(event)">
                <div class="form-group">
                    <label>URL *</label>
                    <input type="url" id="webhookUrl" required>
                </div>
                <div class="form-group">
                    <label>Event Type *</label>
                    <select id="webhookEvent" required>
                        <option value="product.imported">Product Imported</option>
                        <option value="product.created">Product Created</option>
                        <option value="product.updated">Product Updated</option>
                        <option value="product.deleted">Product Deleted</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>
                        <input type="checkbox" id="webhookEnabled" checked> Enabled
                    </label>
                </div>
                <button type="submit">Save</button>
                <button type="button" class="secondary" onclick="closeModal('webhookModal')">Cancel</button>
            </form>
        </div>
    </div>

    <script>
        let currentPage = 1;
        let currentProductId = null;
        let currentWebhookId = null;

        // Upload Functions
        async function uploadFile() {
            const fileInput = document.getElementById('fileInput');
            const file = fileInput.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('file', file);

            try {
                document.getElementById('progressBar').style.display = 'block';
                showStatus('uploadStatus', 'Uploading file...', 'info');

                const response = await fetch('/api/upload', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();
                
                if (response.ok) {
                    trackProgress(data.task_id);
                } else {
                    showStatus('uploadStatus', data.detail || 'Upload failed', 'error');
                }
            } catch (error) {
                showStatus('uploadStatus', 'Upload error: ' + error.message, 'error');
            }
        }

        async function trackProgress(taskId) {
            const interval = setInterval(async () => {
                try {
                    const response = await fetch(`/api/upload/status/${taskId}`);
                    const data = await response.json();

                    const progress = data.progress || 0;
                    const total = data.total || 100;
                    const percentage = total > 0 ? Math.round((progress / total) * 100) : 0;

                    document.getElementById('progressFill').style.width = percentage + '%';
                    document.getElementById('progressFill').textContent = percentage + '%';
                    showStatus('uploadStatus', data.message || 'Processing...', 'info');

                    if (data.status === 'Complete') {
                        clearInterval(interval);
                        showStatus('uploadStatus', data.message, 'success');
                        loadProducts();
                    } else if (data.status === 'Failed') {
                        clearInterval(interval);
                        showStatus('uploadStatus', data.message, 'error');
                    }
                } catch (error) {
                    clearInterval(interval);
                    showStatus('uploadStatus', 'Error tracking progress', 'error');
                }
            }, 1000);
        }

        // Product Functions
        async function loadProducts(page = 1) {
            const sku = document.getElementById('searchSku').value;
            const name = document.getElementById('searchName').value;
            const active = document.getElementById('filterActive').value;

            let url = `/api/products?page=${page}&limit=20`;
            if (sku) url += `&sku=${sku}`;
            if (name) url += `&name=${name}`;
            if (active) url += `&active=${active}`;

            const response = await fetch(url);
            const data = await response.json();

            const tbody = document.getElementById('productsBody');
            tbody.innerHTML = '';

            data.products.forEach(product => {
                const row = tbody.insertRow();
                row.innerHTML = `
                    <td>${product.sku}</td>
                    <td>${product.name}</td>
                    <td>${product.description || ''}</td>
                    <td>${product.active ? '✅ Active' : '❌ Inactive'}</td>
                    <td class="actions">
                        <button class="btn-sm" onclick="editProduct(${product.id})">Edit</button>
                        <button class="btn-sm danger" onclick="deleteProduct(${product.id})">Delete</button>
                    </td>
                `;
            });

            renderPagination(data.total, data.page, data.limit);
        }

        function renderPagination(total, page, limit) {
            const totalPages = Math.ceil(total / limit);
            const pagination = document.getElementById('pagination');
            pagination.innerHTML = '';

            if (totalPages <= 1) return;

            if (page > 1) {
                const prev = document.createElement('button');
                prev.textContent = '← Previous';
                prev.onclick = () => loadProducts(page - 1);
                pagination.appendChild(prev);
            }

            const info = document.createElement('span');
            info.textContent = `Page ${page} of ${totalPages}`;
            info.style.padding = '10px';
            pagination.appendChild(info);

            if (page < totalPages) {
                const next = document.createElement('button');
                next.textContent = 'Next →';
                next.onclick = () => loadProducts(page + 1);
                pagination.appendChild(next);
            }
        }

        async function saveProduct(event) {
            event.preventDefault();
            
            const product = {
                sku: document.getElementById('productSku').value,
                name: document.getElementById('productName').value,
                description: document.getElementById('productDescription').value,
                active: document.getElementById('productActive').checked
            };

            const url = currentProductId 
                ? `/api/products/${currentProductId}` 
                : '/api/products';
            const method = currentProductId ? 'PUT' : 'POST';

            const response = await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(product)
            });

            if (response.ok) {
                closeModal('productModal');
                loadProducts();
            } else {
                const error = await response.json();
                alert('Error: ' + (error.detail || 'Failed to save product'));
            }
        }

        async function editProduct(id) {
            const response = await fetch(`/api/products/${id}`);
            const product = await response.json();

            currentProductId = id;
            document.getElementById('modalTitle').textContent = 'Edit Product';
            document.getElementById('productSku').value = product.sku;
            document.getElementById('productName').value = product.name;
            document.getElementById('productDescription').value = product.description || '';
            document.getElementById('productActive').checked = product.active;

            document.getElementById('productModal').style.display = 'block';
        }

        function openAddModal() {
            currentProductId = null;
            document.getElementById('modalTitle').textContent = 'Add Product';
            document.getElementById('productForm').reset();
            document.getElementById('productModal').style.display = 'block';
        }

        async function deleteProduct(id) {
            if (!confirm('Delete this product?')) return;

            const response = await fetch(`/api/products/${id}`, { method: 'DELETE' });
            if (response.ok) {
                loadProducts();
            }
        }

        async function confirmBulkDelete() {
            if (!confirm('⚠️ WARNING: This will delete ALL products. This cannot be undone. Are you sure?')) return;
            if (!confirm('Final confirmation: Delete all products?')) return;

            const response = await fetch('/api/products/bulk-delete', { method: 'DELETE' });
            const data = await response.json();
            
            if (response.ok) {
                alert(data.message);
                loadProducts();
            }
        }

        // Webhook Functions
        async function loadWebhooks() {
            const response = await fetch('/api/webhooks');
            const webhooks = await response.json();

            const tbody = document.getElementById('webhooksBody');
            tbody.innerHTML = '';

            webhooks.forEach(webhook => {
                const row = tbody.insertRow();
                row.innerHTML = `
                    <td>${webhook.url}</td>
                    <td>${webhook.event_type}</td>
                    <td>${webhook.enabled ? '✅ Enabled' : '❌ Disabled'}</td>
                    <td class="actions">
                        <button class="btn-sm" onclick="testWebhook(${webhook.id})">Test</button>
                        <button class="btn-sm danger" onclick="deleteWebhook(${webhook.id})">Delete</button>
                    </td>
                `;
            });
        }

        async function saveWebhook(event) {
            event.preventDefault();

            const webhook = {
                url: document.getElementById('webhookUrl').value,
                event_type: document.getElementById('webhookEvent').value,
                enabled: document.getElementById('webhookEnabled').checked
            };

            const response = await fetch('/api/webhooks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(webhook)
            });

            if (response.ok) {
                closeModal('webhookModal');
                loadWebhooks();
            }
        }

        async function testWebhook(id) {
            const response = await fetch(`/api/webhooks/${id}/test`, { method: 'POST' });
            const data = await response.json();
            alert(data.message || 'Webhook tested');
        }

        async function deleteWebhook(id) {
            if (!confirm('Delete this webhook?')) return;

            const response = await fetch(`/api/webhooks/${id}`, { method: 'DELETE' });
            if (response.ok) {
                loadWebhooks();
            }
        }

        function openWebhookModal() {
            document.getElementById('webhookForm').reset();
            document.getElementById('webhookModal').style.display = 'block';
        }

        // Utility Functions
        function closeModal(modalId) {
            document.getElementById(modalId).style.display = 'none';
        }

        function showStatus(elementId, message, type) {
            const element = document.getElementById(elementId);
            element.innerHTML = `<div class="status ${type}">${message}</div>`;
        }

        // Initialize
        loadProducts();
        loadWebhooks();
    </script>
</body>
</html>
    """

# API Endpoints - [Keep all the same endpoints from previous code]

@app.post("/api/upload")
async def upload_csv(file: UploadFile = File(...)):
    """Upload CSV file for processing"""
    try:
        content = await file.read()
        csv_content = content.decode('utf-8')
        
        # Start Celery task
        task = process_csv_upload.delay(csv_content)
        
        return {"task_id": task.id, "message": "Upload started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/upload/status/{task_id}")
async def upload_status(task_id: str):
    """Get upload progress status"""
    task = celery_app.AsyncResult(task_id)
    
    if task.state == 'PENDING':
        response = {
            'status': 'Pending',
            'progress': 0,
            'total': 0,
            'message': 'Task is waiting to start...'
        }
    elif task.state == 'PROGRESS':
        response = task.info
    elif task.state == 'SUCCESS':
        response = task.result
    else:
        response = {
            'status': 'Failed',
            'progress': 0,
            'total': 0,
            'message': str(task.info)
        }
    
    return response

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
        query = query.filter(Product.active == active)
    
    total = query.count()
    products = query.offset((page - 1) * limit).limit(limit).all()
    
    return {
        "products": products,
        "total": total,
        "page": page,
        "limit": limit
    }

@app.get("/api/products/{product_id}", response_model=ProductSchema)
async def get_product(product_id: int, db: Session = Depends(get_db)):
    """Get single product"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@app.post("/api/products", response_model=ProductSchema)
async def create_product(product: ProductCreate, db: Session = Depends(get_db)):
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
    
    trigger_webhooks(db, 'product.created', {'sku': db_product.sku})
    
    return db_product

@app.put("/api/products/{product_id}", response_model=ProductSchema)
async def update_product(
    product_id: int,
    product: ProductUpdate,
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
    
    trigger_webhooks(db, 'product.updated', {'sku': db_product.sku})
    
    return db_product

@app.delete("/api/products/{product_id}")
async def delete_product(product_id: int, db: Session = Depends(get_db)):
    """Delete product"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    db.delete(product)
    db.commit()
    
    trigger_webhooks(db, 'product.deleted', {'sku': product.sku})
    
    return {"message": "Product deleted"}

@app.delete("/api/products/bulk-delete")
async def bulk_delete_products(db: Session = Depends(get_db)):
    """Delete all products"""
    count = db.query(Product).count()
    db.query(Product).delete()
    db.commit()
    
    return {"message": f"Deleted {count} products"}

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
