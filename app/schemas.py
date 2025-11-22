from pydantic import BaseModel
from typing import Optional

class ProductBase(BaseModel):
    sku: str
    name: str
    description: Optional[str] = None
    active: bool = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(ProductBase):
    pass

class Product(ProductBase):
    id: int
    
    class Config:
        from_attributes = True

class WebhookBase(BaseModel):
    url: str
    event_type: str
    enabled: bool = True

class WebhookCreate(WebhookBase):
    pass

class Webhook(WebhookBase):
    id: int
    
    class Config:
        from_attributes = True

class UploadProgress(BaseModel):
    status: str
    progress: int
    total: int
    message: str
