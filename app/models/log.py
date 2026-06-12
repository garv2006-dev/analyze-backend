from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from backend.app.database import Base

class Log(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type = Column(String(50), nullable=False, index=True) # "MONITORING_START", "MONITORING_STOP", "SCREENSHOT_CAPTURE", "AI_PREDICTION", "RATE_LIMIT_BLOCKED", "AUTH_LOGIN", "AUTH_REGISTER"
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "event_type": self.event_type,
            "message": self.message,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
