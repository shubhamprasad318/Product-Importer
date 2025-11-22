import csv
import io
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

from app.database import SessionLocal
from app.models import Product, Webhook
from sqlalchemy import func
import httpx
import logging

logger = logging.getLogger(__name__)

def process_csv_upload(csv_content: str):
    """Process CSV file upload synchronously"""
    db = SessionLocal()
    try:
        csv_file = io.StringIO(csv_content)
        reader = csv.DictReader(csv_file)
        
        processed = 0
        batch_size = 1000
        batch = []
        
        for row in reader:
            sku = row.get('sku', '').strip()
            name = row.get('name', '').strip()
            description = row.get('description', '').strip()
            
            if not sku or not name:
                continue
            
            batch.append({
                'sku': sku,
                'name': name,
                'description': description,
                'active': True
            })
            
            processed += 1
            
            if len(batch) >= batch_size:
                upsert_products(db, batch)
                batch = []
        
        # Process remaining batch
        if batch:
            upsert_products(db, batch)
        
        # Trigger webhooks
        trigger_webhooks('product.imported', {'count': processed})
        
        return {
            'status': 'Complete',
            'progress': processed,
            'total': processed,
            'message': f'Successfully imported {processed} products'
        }
    
    except Exception as e:
        logger.error(f"Error processing CSV: {str(e)}")
        raise
    finally:
        db.close()

def upsert_products(db, products):
    """Bulk upsert products with case-insensitive SKU matching"""
    for product_data in products:
        # Check for existing product (case-insensitive)
        existing = db.query(Product).filter(
            func.lower(Product.sku) == func.lower(product_data['sku'])
        ).first()
        
        if existing:
            # Update existing
            existing.name = product_data['name']
            existing.description = product_data['description']
            existing.active = product_data.get('active', True)
        else:
            # Create new
            new_product = Product(**product_data)
            db.add(new_product)
    
    db.commit()

def trigger_webhooks(event_type: str, data: dict):
    """Trigger all enabled webhooks for the event type"""
    # Create a new session (works for both sync and background tasks)
    db = SessionLocal()
    try:
        webhooks = db.query(Webhook).filter(
            Webhook.event_type == event_type,
            Webhook.enabled == True
        ).all()
        
        for webhook in webhooks:
            try:
                with httpx.Client(timeout=10.0) as client:
                    client.post(webhook.url, json={'event': event_type, 'data': data})
            except Exception as e:
                logger.error(f"Webhook error for {webhook.url}: {str(e)}")
    finally:
        db.close()
