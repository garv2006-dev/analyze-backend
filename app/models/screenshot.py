from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from backend.app.database import Base
from backend.app.config import BACKEND_URL

class Screenshot(Base):
    __tablename__ = "screenshots"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    url_id = Column(Integer, ForeignKey("target_urls.id", ondelete="CASCADE"), nullable=False, index=True)
    image_path = Column(String(512), nullable=False)
    highlighted_image_path = Column(String(512), nullable=True) # visual differences highlight image path
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "url_id": self.url_id,
            "image_path": self.image_path,
            "image_url": self.image_path if (self.image_path and (self.image_path.startswith("http://") or self.image_path.startswith("https://"))) else f"{BACKEND_URL}/screenshots/{self.image_path}",
            "highlighted_image_path": self.highlighted_image_path,
            "highlighted_image_url": self.highlighted_image_path if (self.highlighted_image_path and (self.highlighted_image_path.startswith("http://") or self.highlighted_image_path.startswith("https://"))) else (f"{BACKEND_URL}/screenshots/{self.highlighted_image_path}" if self.highlighted_image_path else None),
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
