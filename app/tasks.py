import pandas as pd
import io
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import Product, Webhook
import httpx
import json

@celery_app.task(bind=True)
def import_products_task(self, csv_content: str):
    """
    Import products from CSV content with progress tracking.
    Handles large files efficiently with batch processing.
    """
    db = SessionLocal()
    
    try:
        # Update task state
        self.update_state(state='PROGRESS', meta={'progress': 0, 'total': 0, 'message': 'Parsing CSV'})
        
        # Parse CSV
        csv_file = io.StringIO(csv_content)
        df = pd.read_csv(csv_file)
        
        total_rows = len(df)
        self.update_state(state='PROGRESS', meta={'progress': 0, 'total': total_rows, 'message': 'Validating data'})
        
        # Clean and prepare data
        df.columns = df.columns.str.strip().str.lower()
        
        # Ensure required columns exist
        required_cols = ['sku', 'name']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")
        
        # Process in batches for better performance
        batch_size = 1000
        processed = 0
        
        for start_idx in range(0, total_rows, batch_size):
            end_idx = min(start_idx + batch_size, total_rows)
            batch_df = df.iloc[start_idx:end_idx]
            
            # Prepare batch data
            products_data = []
            for _, row in batch_df.iterrows():
                product_dict = {
                    'sku': str(row['sku']).strip(),
                    'name': str(row['name']).strip(),
                    'description': str(row.get('description', '')) if pd.notna(row.get('description')) else None,
                    'price': float(row['price']) if 'price' in row and pd.notna(row['price']) else None,
                    'is_active': True
                }
                products_data.append(product_dict)
            
            # Bulk upsert using PostgreSQL's INSERT ... ON CONFLICT
            stmt = insert(Product).values(products_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=['sku'],
                set_={
                    'name': stmt.excluded.name,
                    'description': stmt.excluded.description,
                    'price': stmt.excluded.price,
                    'is_active': stmt.excluded.is_active
                }
            )
            
            db.execute(stmt)
            db.commit()
            
            processed += len(batch_df)
            progress = int((processed / total_rows) * 100)
            
            self.update_state(
                state='PROGRESS',
                meta={
                    'progress': processed,
                    'total': total_rows,
                    'message': f'Imported {processed}/{total_rows} products'
                }
            )
        
        # Trigger webhooks
        trigger_webhooks.delay('product.import.completed', {'total': total_rows})
        
        return {
            'status': 'completed',
            'progress': total_rows,
            'total': total_rows,
            'message': f'Successfully imported {total_rows} products'
        }
        
    except Exception as e:
        db.rollback()
        self.update_state(state='FAILURE', meta={'message': str(e)})
        raise
    finally:
        db.close()

@celery_app.task
def trigger_webhooks(event_type: str, payload: dict):
    """
    Trigger all enabled webhooks for a given event type.
    """
    db = SessionLocal()
    
    try:
        webhooks = db.query(Webhook).filter(
            Webhook.event_type == event_type,
            Webhook.is_enabled == True
        ).all()
        
        for webhook in webhooks:
            try:
                with httpx.Client(timeout=10.0) as client:
                    response = client.post(
                        webhook.url,
                        json={'event': event_type, 'data': payload},
                        headers={'Content-Type': 'application/json'}
                    )
                    response.raise_for_status()
            except Exception as e:
                # Log error but continue with other webhooks
                print(f"Webhook error for {webhook.url}: {str(e)}")
                
    finally:
        db.close()