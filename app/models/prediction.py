from sqlalchemy import Column, Integer, String, DateTime, Text, JSON
from sqlalchemy.sql import func
from backend.app.database import Base

class StockPrediction(Base):
    __tablename__ = "stock_predictions"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    stock_symbol = Column(String(50), nullable=False, index=True)
    captured_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    image_path = Column(String(255), nullable=False)
    trend_direction = Column(String(20), nullable=False) # BULLISH, BEARISH, SIDEWAYS
    confidence_score = Column(Integer, nullable=False)
    support_levels = Column(JSON, nullable=False) # JSON array of floats e.g. [23650, 23620]
    resistance_levels = Column(JSON, nullable=False) # JSON array of floats e.g. [23780, 23820]
    prediction_json = Column(JSON, nullable=False) # Dictionary detailing forecast intervals & indicators
    ai_summary = Column(Text, nullable=False)

    def to_dict(self):
        """Converts SQLAlchemy model to a serializable dictionary, maintaining backward compatibility for legacy frontend properties."""
        
        # Determine the first support/resistance level for legacy support
        legacy_support = 0.0
        legacy_resistance = 0.0
        if isinstance(self.support_levels, list) and len(self.support_levels) > 0:
            legacy_support = float(self.support_levels[0])
        elif isinstance(self.support_levels, (int, float)):
            legacy_support = float(self.support_levels)
            
        if isinstance(self.resistance_levels, list) and len(self.resistance_levels) > 0:
            legacy_resistance = float(self.resistance_levels[0])
        elif isinstance(self.resistance_levels, (int, float)):
            legacy_resistance = float(self.resistance_levels)

        # Reconstruct extracted metrics & forecast results for legacy UI components
        indicators = self.prediction_json.get("indicators", {}) if isinstance(self.prediction_json, dict) else {}
        current_value = self.prediction_json.get("current_value", legacy_support * 1.01) # sensible default
        
        # Build backward-compatible JSON structure
        return {
            "id": self.id,
            "stock_symbol": self.stock_symbol,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "image_path": self.image_path,
            "image_url": f"/screenshots/{self.image_path}",
            "trend_direction": self.trend_direction,
            "confidence_score": self.confidence_score,
            "support_levels": self.support_levels,
            "resistance_levels": self.resistance_levels,
            "prediction_json": self.prediction_json,
            "ai_summary": self.ai_summary,
            
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
                "forecast_trend": self.trend_direction.lower(),
                "confidence_score": self.confidence_score,
                "prediction_summary": self.ai_summary
            }
        }
