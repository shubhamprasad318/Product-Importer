from sqlalchemy import Column, Integer, String, Text, Boolean, Index
from app.database import Base

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(500), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)  # Changed from 'active' to 'is_active'
    
    # Add property for compatibility
    @property
    def active(self):
        return self.is_active
    
    @active.setter
    def active(self, value):
        self.is_active = value

class Webhook(Base):
    __tablename__ = "webhooks"
    
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String(500), nullable=False)
    event_type = Column(String(100), nullable=False)
    is_enabled = Column(Boolean, default=True)  # Changed from 'enabled' to 'is_enabled'
    
    # Add property for compatibility
    @property
    def enabled(self):
        return self.is_enabled
    
    @enabled.setter
    def enabled(self, value):
        self.is_enabled = value
