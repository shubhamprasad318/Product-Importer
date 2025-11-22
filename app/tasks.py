import csv
import io
from dotenv import load_dotenv
import os
import time

# Load environment variables
load_dotenv()

from app.database import SessionLocal
from app.models import Product, Webhook
from sqlalchemy import func
from sqlalchemy.exc import OperationalError
import httpx
import logging

logger = logging.getLogger(__name__)

def process_csv_upload(csv_content: str):
    """Process CSV file upload synchronously with connection recovery"""
    try:
        csv_file = io.StringIO(csv_content)
        reader = csv.DictReader(csv_file)
        
        processed = 0
        created = 0
        updated = 0
        batch_size = 50  # Reduced for free tier stability
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
                'description': description
            })
            
            # Process in smaller batches
            if len(batch) >= batch_size:
                result = upsert_products_batch(batch)
                created += result['created']
                updated += result['updated']
                processed += len(batch)
                batch = []
                
                # Small delay to prevent connection issues
                time.sleep(0.1)
        
        # Process remaining batch
        if batch:
            result = upsert_products_batch(batch)
            created += result['created']
            updated += result['updated']
            processed += len(batch)
        
        # Trigger webhooks
        trigger_webhooks('product.imported', {
            'total': processed,
            'created': created,
            'updated': updated
        })
        
        return {
            'status': 'Complete',
            'message': f'Successfully processed {processed} products ({created} created, {updated} updated)',
            'total': processed,
            'created': created,
            'updated': updated
        }
    
    except Exception as e:
        logger.error(f"Error processing CSV: {str(e)}")
        return {
            'status': 'Failed',
            'message': f'Error: {str(e)}',
            'total': 0
        }

def upsert_products_batch(batch, max_retries=3):
    """Bulk upsert products with retry logic"""
    created = 0
    updated = 0
    
    for retry in range(max_retries):
        db = SessionLocal()
        try:
            for product_data in batch:
                # Check for existing product (case-insensitive)
                existing = db.query(Product).filter(
                    func.lower(Product.sku) == func.lower(product_data['sku'])
                ).first()
                
                if existing:
                    # Update existing
                    existing.name = product_data['name']
                    existing.description = product_data['description']
                    existing.is_active = True  # Fixed: was 'active'
                    updated += 1
                else:
                    # Create new
                    new_product = Product(
                        sku=product_data['sku'],
                        name=product_data['name'],
                        description=product_data['description'],
                        is_active=True  # Fixed: was 'active'
                    )
                    db.add(new_product)
                    created += 1
            
            db.commit()
            return {'created': created, 'updated': updated}
            
        except OperationalError as e:
            logger.warning(f"Database connection error, retry {retry + 1}/{max_retries}: {str(e)}")
            db.rollback()
            if retry < max_retries - 1:
                time.sleep(1)  # Wait before retry
                continue
            else:
                # Return what we've processed so far
                logger.error(f"Failed after {max_retries} retries")
                return {'created': 0, 'updated': 0}
        except Exception as e:
            logger.error(f"Error processing batch: {str(e)}")
            db.rollback()
            return {'created': 0, 'updated': 0}
        finally:
            db.close()
    
    return {'created': 0, 'updated': 0}

def trigger_webhooks(event_type: str, data: dict):
    """Trigger all enabled webhooks for the event type"""
    db = SessionLocal()
    try:
        webhooks = db.query(Webhook).filter(
            Webhook.event_type == event_type,
            Webhook.is_enabled == True  # Fixed: was 'enabled'
        ).all()
        
        for webhook in webhooks:
            try:
                with httpx.Client(timeout=10.0) as client:
                    client.post(webhook.url, json={'event': event_type, 'data': data})
            except Exception as e:
                logger.error(f"Webhook error for {webhook.url}: {str(e)}")
    except Exception as e:
        logger.error(f"Error fetching webhooks: {str(e)}")
    finally:
        db.close()
