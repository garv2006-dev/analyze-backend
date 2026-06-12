from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from backend.app.database import Base

class RateLimit(Base):
    __tablename__ = "rate_limits"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    request_count = Column(Integer, default=0, nullable=False)
    time_window = Column(String(50), nullable=False, index=True) # e.g. "2026-06-12_14:55_min", "2026-06-12_14_hour", "2026-06-12_day"
    last_request_time = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "request_count": self.request_count,
            "time_window": self.time_window,
            "last_request_time": self.last_request_time.isoformat() if self.last_request_time else None,
        }
