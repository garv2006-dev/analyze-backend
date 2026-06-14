from sqlalchemy import Column, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from backend.app.database import Base
from backend.app.config import BACKEND_URL

class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    screenshot_id = Column(Integer, ForeignKey("screenshots.id", ondelete="CASCADE"), nullable=False, index=True)
    ai_result = Column(JSON, nullable=False) # JSON details containing supports, resistances, summaries, sentiment
    confidence_score = Column(Integer, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def to_dict(self, screenshot_path=None, highlighted_path=None, stock_symbol=None):
        """Converts SQLAlchemy model to a serializable dictionary, maintaining backward compatibility for legacy frontend properties."""
        ai_res = self.ai_result or {}
        
        support_levels = ai_res.get("support_levels", [])
        resistance_levels = ai_res.get("resistance_levels", [])
        
        legacy_support = 0.0
        legacy_resistance = 0.0
        if isinstance(support_levels, list) and len(support_levels) > 0:
            legacy_support = float(support_levels[0])
        if isinstance(resistance_levels, list) and len(resistance_levels) > 0:
            legacy_resistance = float(resistance_levels[0])
            
        current_value = ai_res.get("current_value", legacy_support * 1.01)
        indicators = ai_res.get("indicators", {})
        
        img_path = screenshot_path or ""
        img_url = img_path if (img_path and (img_path.startswith("http://") or img_path.startswith("https://"))) else (f"{BACKEND_URL}/screenshots/{img_path}" if img_path else "")
        
        highlight_url = highlighted_path if (highlighted_path and (highlighted_path.startswith("http://") or highlighted_path.startswith("https://"))) else (f"{BACKEND_URL}/screenshots/{highlighted_path}" if highlighted_path else None)

        ts = self.timestamp
        if ts:
            from datetime import timezone
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            captured_at_str = ts.isoformat()
        else:
            captured_at_str = None

        return {
            "id": self.id,
            "stock_symbol": stock_symbol or "TARGET",
            "captured_at": captured_at_str,
            "image_path": img_path,
            "image_url": img_url,
            "highlighted_image_url": highlight_url,
            "trend_direction": ai_res.get("trend_direction", "SIDEWAYS").upper(),
            "confidence_score": self.confidence_score,
            "support_levels": support_levels,
            "resistance_levels": resistance_levels,
            "prediction_json": ai_res,
            "ai_summary": ai_res.get("ai_summary", ""),
            "is_mock": ai_res.get("is_mock", False),
            
            # Legacy structures for existing frontend components:
            "extracted_metrics": {
                "current_value": float(current_value),
                "support_level": legacy_support,
                "resistance_level": legacy_resistance,
                "indicators": {
                    "rsi": indicators.get("rsi", 50),
                    "macd_trend": indicators.get("macd_trend", "Neutral")
                }
            },
            "forecast_results": {
                "forecast_trend": ai_res.get("trend_direction", "SIDEWAYS").lower(),
                "confidence_score": self.confidence_score,
                "prediction_summary": ai_res.get("ai_summary", "")
            }
        }
