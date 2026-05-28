import torch
import torch.nn as nn
import torch.nn.functional as F

class StockQuantNet(nn.Module):
    """
    A dual-headed Deep Learning Neural Network designed for local stock graph and price predictions.
    It takes quantitative features (current price, asset symbol index, hour of day, day of week)
    and predicts both classification targets (Trend Direction) and regression targets
    (Confidence Score, Support Levels, and Resistance Levels).
    """
    def __init__(self, input_dim=8, num_symbols=10, hidden_dim=64):
        super(StockQuantNet, self).__init__()
        
        # Symbol Embedding Layer to learn dense representation of stock symbols
        self.symbol_embedding = nn.Embedding(num_symbols, 8)
        
        # Shared Feature Extractor Layers
        self.fc1 = nn.Linear(input_dim - 1 + 8, hidden_dim) # numerical inputs + symbol embedding
        self.bn1 = nn.BatchNorm1d(hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.bn2 = nn.BatchNorm1d(hidden_dim)
        self.dropout = nn.Dropout(0.2)
        
        # --- Head 1: Trend Classification Head ---
        # Predicts probabilities for [BULLISH, BEARISH, SIDEWAYS]
        self.trend_layer1 = nn.Linear(hidden_dim, 32)
        self.trend_out = nn.Linear(32, 3)
        
        # --- Head 2: Regression Head ---
        # Predicts: [confidence_score, support_1, support_2, resistance_1, resistance_2]
        self.reg_layer1 = nn.Linear(hidden_dim, 32)
        self.reg_out = nn.Linear(32, 5)
        
    def forward(self, x_numerical, x_symbol):
        # 1. Embed the asset symbol index
        symbol_embed = self.symbol_embedding(x_symbol) # Shape: (batch_size, 8)
        
        # 2. Concatenate numerical features and dense symbol embedding
        x = torch.cat([x_numerical, symbol_embed], dim=1) # Shape: (batch_size, input_dim - 1 + 8)
        
        # 3. Pass through shared dense representation layers
        x = F.relu(self.bn1(self.fc1(x)))
        x = self.dropout(x)
        x = F.relu(self.bn2(self.fc2(x)))
        
        # 4. Route to classification head (Trend Direction)
        t = F.relu(self.trend_layer1(x))
        trend_logits = self.trend_out(t) # Raw logits for Cross-Entropy loss
        
        # 5. Route to regression head (Confidence & S/R Boundaries)
        r = F.relu(self.reg_layer1(x))
        reg_predictions = self.reg_out(r) # Outputs e.g. [confidence, s1, s2, r1, r2]
        
        return trend_logits, reg_predictions
