from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from backend.app.database import Base


class SavedAsset(Base):
    """Persistent database model for user-saved watchlist assets (symbol + chart URL)."""
    __tablename__ = "saved_assets"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    symbol = Column(String(50), nullable=False, unique=True, index=True)
    url = Column(String(1024), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "url": self.url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
