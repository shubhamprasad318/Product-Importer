import csv
import io
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import Product, Webhook
from sqlalchemy import func
import httpx
import logging

logger = logging.getLogger(__name__)

@celery_app.task(bind=True)
def process_csv_upload(self, csv_content: str):
    """Process CSV file upload with progress tracking"""
    db = SessionLocal()
    try:
        csv_file = io.StringIO(csv_content)
        reader = csv.DictReader(csv_file)
        
        total_rows = csv_content.count('\n') - 1
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
                
                # Update progress
                progress = int((processed / total_rows) * 100)
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'status': 'Processing',
                        'progress': processed,
                        'total': total_rows,
                        'message': f'Processed {processed} of {total_rows} products'
                    }
                )
        
        # Process remaining batch
        if batch:
            upsert_products(db, batch)
        
        # Trigger webhooks
        trigger_webhooks(db, 'product.imported', {'count': processed})
        
        return {
            'status': 'Complete',
            'progress': total_rows,
            'total': total_rows,
            'message': f'Successfully imported {processed} products'
        }
    
    except Exception as e:
        logger.error(f"Error processing CSV: {str(e)}")
        return {
            'status': 'Failed',
            'progress': 0,
            'total': 0,
            'message': f'Error: {str(e)}'
        }
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

def trigger_webhooks(db, event_type: str, data: dict):
    """Trigger all enabled webhooks for the event type"""
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
