from sqlalchemy import Column, Integer, ForeignKey
from backend.app.database import Base

class HiddenPrediction(Base):
    __tablename__ = "hidden_predictions"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    # Store the prediction ID that is hidden. We don't use a strict foreign key constraint 
    # to avoid migration issues with existing databases, but logically it maps to stock_predictions.id
    prediction_id = Column(Integer, unique=True, nullable=False, index=True)
