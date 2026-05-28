import os
from pathlib import Path
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, random_split
from backend.app.ml.model import StockQuantNet

CHECKPOINT_DIR = Path(__file__).resolve().parent / "checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

def train_local_model(dataset, epochs=50, batch_size=8, learning_rate=0.001):
    """
    Trains the local dual-headed neural network model on compiled supervised data
    and saves the optimized weights.
    """
    if len(dataset) < 4:
        print("⚠️ Not enough dataset samples to train. Collect at least 5 AI predictions first!")
        return False
        
    print(f"📊 Initializing Training: Compiled {len(dataset)} prediction records for local learning.")
    
    # 1. Train/Validation Split (80% train, 20% validation)
    val_size = max(1, int(len(dataset) * 0.2))
    train_size = len(dataset) - val_size
    train_set, val_set = random_split(dataset, [train_size, val_size])
    
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False)
    
    # 2. Build Model & Optimizer
    model = StockQuantNet(input_dim=3, num_symbols=10, hidden_dim=64)
    optimizer = optim.Adam(model.parameters(), lr=learning_rate, weight_decay=1e-5)
    
    # 3. Define Multi-task Loss Functions
    classification_loss_fn = nn.CrossEntropyLoss()
    regression_loss_fn = nn.MSELoss()
    
    best_val_loss = float('inf')
    
    print("🚀 Supervised Local Model Training Cycle Started...")
    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = 0.0
        correct_trends = 0
        total_samples = 0
        
        for x_num, x_sym, y_trend, y_reg in train_loader:
            optimizer.zero_grad()
            
            # Forward pass
            trend_logits, reg_preds = model(x_num, x_sym)
            
            # Loss calculations
            loss_trend = classification_loss_fn(trend_logits, y_trend)
            loss_reg = regression_loss_fn(reg_preds, y_reg)
            
            # Combine losses with appropriate scaling weights
            total_loss = loss_trend + 5.0 * loss_reg
            
            # Backpropagation
            total_loss.backward()
            optimizer.step()
            
            train_loss += total_loss.item() * x_num.size(0)
            
            # Calculate classification accuracy
            _, preds = torch.max(trend_logits, 1)
            correct_trends += (preds == y_trend).sum().item()
            total_samples += x_num.size(0)
            
        epoch_loss = train_loss / len(train_set)
        epoch_acc = (correct_trends / total_samples) * 100.0
        
        # 4. Validation Loop
        model.eval()
        val_loss = 0.0
        val_correct = 0
        val_total = 0
        
        with torch.no_grad():
            for x_num, x_sym, y_trend, y_reg in val_loader:
                trend_logits, reg_preds = model(x_num, x_sym)
                
                v_loss_trend = classification_loss_fn(trend_logits, y_trend)
                v_loss_reg = regression_loss_fn(reg_preds, y_reg)
                
                v_total_loss = v_loss_trend + 5.0 * v_loss_reg
                val_loss += v_total_loss.item() * x_num.size(0)
                
                _, preds = torch.max(trend_logits, 1)
                val_correct += (preds == y_trend).sum().item()
                val_total += x_num.size(0)
                
        epoch_val_loss = val_loss / len(val_set)
        epoch_val_acc = (val_correct / val_total) * 100.0 if val_total > 0 else 0.0
        
        if epoch % 10 == 0 or epoch == epochs:
            print(f"Epoch {epoch:02d}/{epochs:02d} | Train Loss: {epoch_loss:.4f} | Train Acc: {epoch_acc:.1f}% | Val Loss: {epoch_val_loss:.4f} | Val Acc: {epoch_val_acc:.1f}%")
            
        # 5. Save best checkpoint
        if epoch_val_loss < best_val_loss:
            best_val_loss = epoch_val_loss
            checkpoint_path = CHECKPOINT_DIR / "best_model.pth"
            torch.save({
                'epoch': epoch,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'val_loss': best_val_loss,
                'price_mean': dataset.price_mean,
                'price_std': dataset.price_std
            }, checkpoint_path)
            
    print(f"✔️ Local model successfully trained! Saved optimal weights to: {CHECKPOINT_DIR / 'best_model.pth'}")
    return True
