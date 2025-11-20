from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class ProductBase(BaseModel):
    sku: str = Field(..., max_length=255)
    name: str = Field(..., max_length=500)
    description: Optional[str] = None
    price: Optional[float] = None
    is_active: bool = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(ProductBase):
    sku: Optional[str] = None
    name: Optional[str] = None
    is_active: Optional[bool] = None

class Product(ProductBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class WebhookBase(BaseModel):
    url: str = Field(..., max_length=1000)
    event_type: str = Field(..., max_length=100)
    is_enabled: bool = True

class WebhookCreate(WebhookBase):
    pass

class WebhookUpdate(BaseModel):
    url: Optional[str] = None
    event_type: Optional[str] = None
    is_enabled: Optional[bool] = None

class Webhook(WebhookBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class UploadResponse(BaseModel):
    task_id: str
    message: str

class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: Optional[int] = None
    total: Optional[int] = None
    message: Optional[str] = None