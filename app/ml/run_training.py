import asyncio
import sys
import os
from pathlib import Path

# Add project root to path to ensure correct package imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from backend.app.database import init_database, SessionLocal
from backend.app.ml.dataset import compile_training_dataset
from backend.app.ml.trainer import train_local_model

async def main():
    print("====================================================")
    print("🧠 LOCAL MACHINE LEARNING TRAINING RUNNER STARTED")
    print("====================================================")
    
    # 1. Initialize Relational Database connection
    print("🔌 Connecting to prediction database...")
    await init_database()
    
    # 2. Compile dataset from prediction logs
    async with SessionLocal() as session:
        print("📊 Querying prediction history and extracting AI vision labels...")
        try:
            dataset = await compile_training_dataset(session)
            
            if len(dataset) < 4:
                print("❌ ERROR: Database has fewer than 5 AI-scraped entries.")
                print("   The local training model needs a solid sample size to learn price structures.")
                print("   Please execute a few more 'Instant Pipeline Trigger' captures on your dashboard first!")
                return
                
            # 3. Train PyTorch neural network
            success = train_local_model(dataset, epochs=100, batch_size=8, learning_rate=0.001)
            
            if success:
                print("\n🎉 SUCCESS: Local quantitative model has successfully learned from the AI!")
                print("   The weights are saved and ready to be separated when you authorize it.")
            else:
                print("\n❌ FAILED: Training cycle aborted.")
                
        except Exception as e:
            print(f"❌ Severe training cycle disruption occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
