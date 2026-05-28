import base64
import json
import logging
import random
from pathlib import Path
from openai import AsyncOpenAI
from PIL import Image
from backend.app import config

# Optional import of Google GenAI SDK
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

logger = logging.getLogger("AI")
logger.setLevel(logging.INFO)

# Global tracker for mock simulation to maintain price continuity
last_mock_value = 23680.50

# Initialize client if not in mock mode
async_client = None
gemini_client = None

if not config.IS_MOCK_MODE:
    if config.IS_GEMINI:
        if genai:
            logger.info("🔌 Initializing official Google GenAI SDK client...")
            gemini_client = genai.Client(api_key=config.OPENAI_API_KEY)
        else:
            logger.warning("⚠️ google-genai SDK is not installed! Falling back to standard OpenAI SDK for Gemini...")
            async_client = AsyncOpenAI(
                api_key=config.OPENAI_API_KEY,
                base_url=config.OPENAI_BASE_URL
            )
    else:
        default_headers = {}
        if config.IS_OPENROUTER:
            if config.OPENROUTER_REFERER:
                default_headers["HTTP-Referer"] = config.OPENROUTER_REFERER
            if config.OPENROUTER_TITLE:
                default_headers["X-OpenRouter-Title"] = config.OPENROUTER_TITLE

        async_client = AsyncOpenAI(
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
            default_headers=default_headers if default_headers else None
        )

def file_to_base64(file_path: str) -> str:
    """Reads a file and converts it into a base64 encoded string."""
    with open(file_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def clean_and_parse_json(s: str) -> dict:
    """
    Cleans and parses a JSON string that may contain markdown wrappers or JavaScript-style comments.
    """
    original = s
    # 1. Strip markdown code block wrappers
    s = s.strip()
    if s.startswith("```"):
        first_newline = s.find("\n")
        if first_newline != -1:
            s = s[first_newline:]
        if s.endswith("```"):
            s = s[:-3]
    s = s.strip()
    
    # 2. Locate first '{' and last '}'
    first_idx = s.find('{')
    last_idx = s.rfind('}')
    if first_idx != -1 and last_idx != -1:
        s = s[first_idx:last_idx+1]
        
    # 3. Remove multi-line comments /* ... */
    import re
    s = re.sub(r'/\*.*?\*/', '', s, flags=re.DOTALL)
    
    # 4. Remove single line comments (// ...) line by line, ignoring comments inside quoted strings
    lines = []
    for line in s.splitlines():
        in_quotes = False
        quote_char = None
        comment_start = -1
        
        i = 0
        while i < len(line):
            char = line[i]
            if char in ['"', "'"]:
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                elif quote_char == char:
                    # check if quote is escaped
                    escaped = False
                    j = i - 1
                    while j >= 0 and line[j] == '\\':
                        escaped = not escaped
                        j -= 1
                    if not escaped:
                        in_quotes = False
                        quote_char = None
            elif char == '/' and i + 1 < len(line) and line[i+1] == '/' and not in_quotes:
                comment_start = i
                break
            i += 1
            
        if comment_start != -1:
            line = line[:comment_start]
        lines.append(line)
        
    s = "\n".join(lines).strip()
    
    # 5. Load JSON
    try:
        return json.loads(s)
    except json.JSONDecodeError as decode_err:
        logger.error(f"Failed to parse JSON even after cleaning. Error: {decode_err}\\nRaw Content:\\n{original}\\nCleaned String:\\n{s}")
        raise

async def analyze_chart(absolute_image_path: str, extracted_price: float = None) -> dict:
    """
    Sends the graph screenshot to OpenAI Vision API for deep market analysis.
    Falls back to synthetic mock data generator if API key is invalid/missing.
    
    Args:
        absolute_image_path (str): The absolute filesystem path of the PNG image.
        extracted_price (float): Dynamic real-time price extracted from page DOM.
        
    Returns:
        dict: Containing trend_direction, confidence_score, support_levels, resistance_levels, prediction_json, ai_summary
    """
    if config.IS_MOCK_MODE:
        logger.info(f"🧠 [MOCK MODE] Simulating stock vision analysis for: {absolute_image_path}")
        return simulate_vision_analysis(extracted_price=extracted_price)
        
    prompt = """You are a highly experienced Senior Quantitative Chart Analyst, Day Trader, and Financial Engineer.
Analyze the provided screenshot of the stock index/asset chart with absolute technical accuracy to extract structured market intelligence and highly precise trend predictions.

### Visual Audit Guidelines for Maximum Accuracy:
1. **Precise Price Extraction**: Examine the right vertical axis (price axis) and any visible dynamic price tag to locate the EXACT current price of the asset. Never invent a price that is not physically visible or scale-accurate.
2. **Candlestick and Momentum Audit**: Carefully analyze the last 5 to 10 candlesticks. Check if they are green (buying pressure) or red (selling pressure), their body-to-wick sizes, and if they represent hammers, engulfing patterns, wicks of rejection, or consecutive trend candles.
3. **Dynamic Support and Resistance Discovery**: Identify clear horizontal price zones where the price has touched and bounced off at least twice in the past. These are your Key Support Levels. Identify overhead ceilings where the price has struggled to break out in recent peaks. These are your Key Resistance Levels.
4. **Indicators Visual Integration**: Visually check for indicators (such as volume bars at the bottom, Moving Average lines crossing candles, RSI, or MACD lines). Incorporate their visual state (e.g., golden cross, oversold, bearish divergence) into your logical reasoning.
5. **Chart Structure & Trend Analysis**: Identify the dominant trend (BULLISH if making higher highs and higher lows; BEARISH if making lower highs and lower lows; SIDEWAYS if oscillating inside a horizontal consolidation channel).
6. **Mathematical Trade Setup Calculation**:
   - Calculate a logical **entry_price** based on breakouts or pullbacks.
   - Set a protective **stop_loss** level (below support for bullish trades, above resistance for bearish trades).
   - Set a realistic **target_price** (take-profit near resistance for bullish trades, near support for bearish trades).
7. **No Placeholder Bias**: Do NOT repeat the example values below. Perform actual visual measurements on the unique chart provided!

Your output must be a clean, valid JSON object following EXACTLY this schema structure:
{
  "trend_direction": "BULLISH", // Must be exactly one of: "BULLISH", "BEARISH", "SIDEWAYS"
  "market_sentiment": "POSITIVE", // Must be exactly one of: "POSITIVE", "NEGATIVE", "NEUTRAL"
  "confidence_score": 92, // Percentage confidence from 0 to 100 based on pattern clarity
  "current_value": 23680.50, // Estimate the exact current asset price shown in the chart
  "support_levels": [
    23650.00,
    23620.00
  ], // Array of 1 to 3 key support levels found on the chart, sorted highest to lowest
  "resistance_levels": [
    23780.00,
    23820.00
  ], // Array of 1 to 3 key resistance levels found on the chart, sorted lowest to highest
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
    "rsi": 64, // Estimate current RSI value between 0 and 100 based on price velocity or visible indicators
    "macd_trend": "Bullish Crossover" // e.g. "Bullish Crossover", "Bearish Divergence", "Neutral", "Consolidation"
  },
  "technical_analysis": {
    "price_action_observations": "Provide a detailed description of the recent candlestick patterns, wick rejections, and overall price direction structure.",
    "support_resistance_rationale": "Explain precisely why the listed support and resistance levels are structurally significant based on the chart's historical peaks/troughs.",
    "indicators_rationale": "Describe the status of the volume, moving averages, or other indicators observed or inferred from the visual price momentum."
  },
  "trade_setup": {
    "entry_price": 23750.00, // Best estimated entry price based on breakout or pullback zones
    "stop_loss": 23710.00, // A strict protection stop-loss level
    "target_price": 23820.00 // A logical take-profit target near next resistance
  },
  "signal": "BUY", // Must be exactly one of: "BUY", "SELL", "HOLD"
  "summary": "Strong bullish continuation detected with breakout potential above resistance." // Professional concise summary
}

Return ONLY the raw JSON object. Do NOT wrap your output in markdown formatting like ```json.
Ensure it is a valid, parseable JSON block."""

    raw_content = ""
    
    try:
        if config.IS_GEMINI and gemini_client:
            logger.info(f"🧠 Initializing active Google GenAI (Gemini) pipeline (model: {config.AI_MODEL})...")
            image = Image.open(absolute_image_path)
            response = await gemini_client.aio.models.generate_content(
                model=config.AI_MODEL,
                contents=[image, prompt],
                config=types.GenerateContentConfig(
                    max_output_tokens=1000,
                    temperature=0.4
                )
            )
            raw_content = response.text.strip()
            logger.info("✔️ Gemini response payload received. Parsing JSON content...")
        else:
            logger.info(f"🧠 Initializing active OpenAI Vision reasoning pipeline (model: {config.AI_MODEL})...")
            base64_image = file_to_base64(absolute_image_path)
            data_url = f"data:image/png;base64,{base64_image}"
            
            response = await async_client.chat.completions.create(
                model=config.AI_MODEL,
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
        
        # Strip markdown syntax wrappers and javascript-style comments using robust parsing
        parsed_data = clean_and_parse_json(raw_content)
        
        # Validate critical root fields exist
        required_keys = ["trend_direction", "confidence_score", "support_levels", "resistance_levels", "summary"]
        for key in required_keys:
            if key not in parsed_data:
                raise ValueError(f"Missing required response field: '{key}'")
                
        # Guide current value and support/resistance if extracted_price is provided
        current_value = parsed_data.get("current_value", sum(parsed_data["support_levels"])/len(parsed_data["support_levels"]) * 1.01)
        if extracted_price is not None:
            current_value = extracted_price
            
        # Re-map parsed structure into table-friendly layout
        return {
            "trend_direction": parsed_data["trend_direction"].upper(),
            "confidence_score": int(parsed_data["confidence_score"]),
            "support_levels": parsed_data["support_levels"],
            "resistance_levels": parsed_data["resistance_levels"],
            "ai_summary": parsed_data["summary"],
            "prediction_json": {
                "current_value": current_value,
                "market_sentiment": parsed_data.get("market_sentiment", "NEUTRAL"),
                "predictions": parsed_data.get("predictions", {}),
                "indicators": parsed_data.get("indicators", {
                    "rsi": 50,
                    "macd_trend": "Neutral"
                }),
                "signal": parsed_data.get("signal", "HOLD"),
                "technical_analysis": parsed_data.get("technical_analysis", {}),
                "trade_setup": parsed_data.get("trade_setup", {}),
                "is_mock": False
            }
        }

        
    except Exception as err:
        logger.error(f"❌ OpenAI Vision analysis failed: {err}")
        logger.warning("⚠️ Falling back to synthetic market simulator due to pipeline disruption.")
        return simulate_vision_analysis(extracted_price=extracted_price)

def simulate_vision_analysis(extracted_price: float = None) -> dict:
    """Generates highly realistic dynamic synthetic mock data representing a real stock index."""
    global last_mock_value
    
    # Anchor the simulation directly to the extracted live price if available
    if extracted_price is not None:
        last_mock_value = float(extracted_price)
        pct_change = (random.random() - 0.42) * 0.04
    else:
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
            "signal": signal,
            "technical_analysis": {
                "price_action_observations": "Sideways candle bodies with low volume indicating consolidation.",
                "support_resistance_rationale": f"Bounces observed at support floor ${s1} and capped at resistance ceiling ${r1}.",
                "indicators_rationale": f"RSI is neutral at {rsi} showing balanced market momentum."
            },
            "trade_setup": {
                "entry_price": round(last_mock_value, 2),
                "stop_loss": s1 if trend == "BULLISH" else round(last_mock_value * 1.015, 2),
                "target_price": r1 if trend == "BULLISH" else round(last_mock_value * 0.985, 2)
            },
            "is_mock": True

        }
    }
