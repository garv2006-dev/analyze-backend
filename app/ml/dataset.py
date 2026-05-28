import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from sqlalchemy.future import select
from backend.app.models.prediction import StockPrediction

# Standard mapping for categorical labels
SYMBOL_MAP = {"NIFTY": 0, "NIFTY50": 0, "BANKNIFTY": 1, "SENSEX": 2, "RELIANCE": 3, "JIO": 4, "HDFC": 5, "OTHER": 6}
TREND_MAP = {"BULLISH": 0, "BEARISH": 1, "SIDEWAYS": 2}

class StockPredictionDataset(Dataset):
    """
    Supervised Machine Learning Dataset that extracts training data directly from
    historical AI Vision predictions.
    """
    def __init__(self, db_records):
        self.numerical_features = []
        self.symbol_indices = []
        self.trend_labels = []
        self.regression_labels = []
        
        for record in db_records:
            # 1. Parse Symbol Index
            clean_symbol = "".join([c for c in record.stock_symbol if not c.isdigit()]).upper().strip()
            symbol_idx = SYMBOL_MAP.get(clean_symbol, SYMBOL_MAP["OTHER"])
            
            # 2. Parse Date/Time features
            dt = record.captured_at
            hour_feat = dt.hour / 24.0
            day_feat = dt.weekday() / 7.0
            
            # 3. Parse target regression levels
            prediction_json = record.prediction_json or {}
            current_price = float(prediction_json.get("current_value", 0))
            if current_price == 0:
                continue # skip uninitialized values
                
            # Scale-normalize prices relative to current price to make model invariant to actual stock price range!
            s_levels = record.support_levels or []
            r_levels = record.resistance_levels or []
            
            # Fallbacks if list lengths vary
            s1 = float(s_levels[0]) / current_price if len(s_levels) > 0 else 0.985
            s2 = float(s_levels[1]) / current_price if len(s_levels) > 1 else 0.970
            r1 = float(r_levels[0]) / current_price if len(r_levels) > 0 else 1.015
            r2 = float(r_levels[1]) / current_price if len(r_levels) > 1 else 1.030
            
            confidence = float(record.confidence_score) / 100.0 # scale to 0.0 - 1.0
            
            # Pack input features
            # Inputs: [normalized_current_price, hour, day_of_week]
            # Since current price is relative, we can pass it normalized or raw
            self.numerical_features.append([current_price, hour_feat, day_feat])
            self.symbol_indices.append(symbol_idx)
            
            # Pack target labels
            trend_str = record.trend_direction.upper().strip()
            self.trend_labels.append(TREND_MAP.get(trend_str, TREND_MAP["SIDEWAYS"]))
            self.regression_labels.append([confidence, s1, s2, r1, r2])
            
        # Convert lists to NumPy arrays
        self.numerical_features = np.array(self.numerical_features, dtype=np.float32)
        self.symbol_indices = np.array(self.symbol_indices, dtype=np.int64)
        self.trend_labels = np.array(self.trend_labels, dtype=np.int64)
        self.regression_labels = np.array(self.regression_labels, dtype=np.float32)
        
        # Simple Z-score normalization for price inputs
        if len(self.numerical_features) > 0:
            self.price_mean = np.mean(self.numerical_features[:, 0])
            self.price_std = np.std(self.numerical_features[:, 0]) + 1e-8
            self.numerical_features[:, 0] = (self.numerical_features[:, 0] - self.price_mean) / self.price_std
        else:
            self.price_mean, self.price_std = 0.0, 1.0
            
    def __len__(self):
        return len(self.trend_labels)
        
    def __getitem__(self, idx):
        return (
            torch.tensor(self.numerical_features[idx], dtype=torch.float32),
            torch.tensor(self.symbol_indices[idx], dtype=torch.long),
            torch.tensor(self.trend_labels[idx], dtype=torch.long),
            torch.tensor(self.regression_labels[idx], dtype=torch.float32)
        )

async def compile_training_dataset(db_session):
    """
    Queries SQLAlchemy database for all authentic AI predictions (is_mock == False)
    and returns a clean PyTorch Dataset.
    """
    # Fetch only authentic high-quality vision predictions (is_mock is False)
    query = select(StockPrediction)
    result = await db_session.execute(query)
    records = result.scalars().all()
    
    # Filter for real predictions (non-mock) to train our local network on actual AI reasoning
    real_records = [r for r in records if not r.prediction_json.get("is_mock", False)]
    
    if len(real_records) < 5:
        # Fallback to include mock records if database is empty, to allow debugging the training loop
        real_records = records
        
    return StockPredictionDataset(real_records)
