import base64
import json
import logging
import random
from pathlib import Path
from openai import AsyncOpenAI
from backend.app import config

logger = logging.getLogger("AI")
logger.setLevel(logging.INFO)

# Global tracker for mock simulation to maintain price continuity
last_mock_value = 23680.50

# Initialize client if not in mock mode
async_client = None
if not config.IS_MOCK_MODE:
    async_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

def file_to_base64(file_path: str) -> str:
    """Reads a file and converts it into a base64 encoded string."""
    with open(file_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

async def analyze_chart(absolute_image_path: str) -> dict:
    """
    Sends the graph screenshot to OpenAI Vision API for deep market analysis.
    Falls back to synthetic mock data generator if API key is invalid/missing.
    
    Args:
        absolute_image_path (str): The absolute filesystem path of the PNG image.
        
    Returns:
        dict: Containing trend_direction, confidence_score, support_levels, resistance_levels, prediction_json, ai_summary
    """
    if config.IS_MOCK_MODE:
        logger.info(f"🧠 [MOCK MODE] Simulating stock vision analysis for: {absolute_image_path}")
        return simulate_vision_analysis()
        
    logger.info("🧠 Initializing active OpenAI Vision reasoning pipeline (model: gpt-4o)...")
    
    try:
        base64_image = file_to_base64(absolute_image_path)
        data_url = f"data:image/png;base64,{base64_image}"
        
        prompt = """You are a highly experienced Senior Quantitative Chart Analyst, Day Trader, and Financial Engineer.
Analyze the provided screenshot of the stock index/asset chart and extract structured intelligence.

Your output must be a clean, valid JSON object following EXACTLY this schema structure:
{
  "trend_direction": "BULLISH", // Must be exactly one of: "BULLISH", "BEARISH", "SIDEWAYS"
  "market_sentiment": "POSITIVE", // Must be exactly one of: "POSITIVE", "NEGATIVE", "NEUTRAL"
  "confidence_score": 92, // Percentage confidence from 0 to 100
  "current_value": 23680.50, // Estimate the current asset price shown in the chart
  "support_levels": [
    23650.00,
    23620.00
  ], // Array of 1 to 3 key support levels found on the chart
  "resistance_levels": [
    23780.00,
    23820.00
  ], // Array of 1 to 3 key resistance levels found on the chart
  "predictions": {
    "15_minutes": {
      "direction": "UP", // Must be exactly: "UP", "DOWN", "SIDEWAYS"
      "confidence": 91
    },
    "1_hour": {
      "direction": "UP",
      "confidence": 87
    },
    "4_hours": {
      "direction": "UP",
      "confidence": 82
    },
    "24_hours": {
      "direction": "UP",
      "confidence": 75
    }
  },
  "indicators": {
    "rsi": 64, // Estimate current RSI value between 0 and 100
    "macd_trend": "Bullish Crossover" // e.g. "Bullish Crossover", "Bearish Divergence", "Neutral", "Consolidation"
  },
  "signal": "BUY", // Must be exactly one of: "BUY", "SELL", "HOLD"
  "summary": "Strong bullish continuation detected with breakout potential above resistance." // Professional concise summary
}

Return ONLY the raw JSON object. Do NOT wrap your output in markdown formatting like ```json.
Ensure it is a valid, parseable JSON block."""

        response = await async_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url
                            }
                        }
                    ]
                }
            ],
            max_tokens=1000
        )
        
        raw_content = response.choices[0].message.content.strip()
        logger.info("✔️ OpenAI response payload received. Parsing JSON content...")
        
        # Strip markdown syntax wrappers if AI returned them
        clean_json = raw_content
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
        clean_json = clean_json.strip()
        
        parsed_data = json.loads(clean_json)
        
        # Validate critical root fields exist
        required_keys = ["trend_direction", "confidence_score", "support_levels", "resistance_levels", "summary"]
        for key in required_keys:
            if key not in parsed_data:
                raise ValueError(f"Missing required response field: '{key}'")
                
        # Re-map parsed structure into table-friendly layout
        return {
            "trend_direction": parsed_data["trend_direction"].upper(),
            "confidence_score": int(parsed_data["confidence_score"]),
            "support_levels": parsed_data["support_levels"],
            "resistance_levels": parsed_data["resistance_levels"],
            "ai_summary": parsed_data["summary"],
            "prediction_json": {
                "current_value": parsed_data.get("current_value", sum(parsed_data["support_levels"])/len(parsed_data["support_levels"]) * 1.01),
                "market_sentiment": parsed_data.get("market_sentiment", "NEUTRAL"),
                "predictions": parsed_data.get("predictions", {}),
                "indicators": parsed_data.get("indicators", {
                    "rsi": 50,
                    "macd_trend": "Neutral"
                }),
                "signal": parsed_data.get("signal", "HOLD")
            }
        }
        
    except Exception as err:
        logger.error(f"❌ OpenAI Vision analysis failed: {err}")
        logger.warning("⚠️ Falling back to synthetic market simulator due to pipeline disruption.")
        return simulate_vision_analysis()

def simulate_vision_analysis() -> dict:
    """Generates highly realistic dynamic synthetic mock data representing a real stock index."""
    global last_mock_value
    
    # Random walk: step price by -1.5% to +2.0% (slight upward bias)
    pct_change = (random.random() - 0.42) * 0.04
    new_value = last_mock_value * (1 + pct_change)
    last_mock_value = round(new_value, 2)
    
    # Calculate support/resistance levels based on price points
    s1 = round(last_mock_value * 0.985, 2)
    s2 = round(last_mock_value * 0.970, 2)
    r1 = round(last_mock_value * 1.015, 2)
    r2 = round(last_mock_value * 1.030, 2)
    
    support_levels = [s1, s2]
    resistance_levels = [r1, r2]
    
    # Standard technical values
    rsi = random.randint(32, 78)
    
    # Determine dynamics based on random walk outcome
    if pct_change > 0.008:
        trend = "BULLISH"
        sentiment = "POSITIVE"
        signal = "BUY"
        macd = "Bullish Crossover"
        summary = (
            f"Strong bullish continuation observed as the price approaches immediate resistance near ${r1}. "
            f"The MACD registers a constructive crossover, and RSI at {rsi} leaves ample scope for further appreciation. "
            f"Recommend adding positions on minor pullbacks."
        )
        pred_15m = "UP"
        pred_1h = "UP"
        pred_4h = "UP"
        pred_24h = "UP"
    elif pct_change < -0.008:
        trend = "BEARISH"
        sentiment = "NEGATIVE"
        signal = "SELL"
        macd = "Bearish Divergence"
        summary = (
            f"The index displays bearish corrective tendencies, having broken below dynamic support levels. "
            f"Profit-taking pressure near ${r1} has forced a retracement towards key support zones near ${s1}. "
            f"Exercise caution and look for stable consolidation before re-entering."
        )
        pred_15m = "DOWN"
        pred_1h = "DOWN"
        pred_4h = "DOWN"
        pred_24h = "DOWN"
    else:
        trend = "SIDEWAYS"
        sentiment = "NEUTRAL"
        signal = "HOLD"
        macd = "Neutral"
        summary = (
            f"The index remains encapsulated in a tight sideways consolidation pattern. "
            f"Trading volumes are subdued, suggesting accumulation. We expect sideways oscillation between "
            f"${s1} and ${r1} until a breakout catalyst occurs."
        )
        pred_15m = "SIDEWAYS"
        pred_1h = "UP"
        pred_4h = "SIDEWAYS"
        pred_24h = "UP"
        
    confidence = random.randint(75, 95)
    
    return {
        "trend_direction": trend,
        "confidence_score": confidence,
        "support_levels": support_levels,
        "resistance_levels": resistance_levels,
        "ai_summary": summary,
        "prediction_json": {
            "current_value": last_mock_value,
            "market_sentiment": sentiment,
            "predictions": {
                "15_minutes": {"direction": pred_15m, "confidence": random.randint(70, 95)},
                "1_hour": {"direction": pred_1h, "confidence": random.randint(70, 95)},
                "4_hours": {"direction": pred_4h, "confidence": random.randint(70, 95)},
                "24_hours": {"direction": pred_24h, "confidence": random.randint(70, 95)}
            },
            "indicators": {
                "rsi": rsi,
                "macd_trend": macd
            },
            "signal": signal
        }
    }
