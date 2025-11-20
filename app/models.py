from sqlalchemy import Column, Integer, String, Text, Boolean, Float, Index
from sqlalchemy.sql import func
from sqlalchemy import DateTime
from app.database import Base

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    __table_args__ = (
        Index('ix_products_sku_lower', func.lower(sku), unique=True),
    )

class Webhook(Base):
    __tablename__ = "webhooks"
    
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String(1000), nullable=False)
    event_type = Column(String(100), nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())