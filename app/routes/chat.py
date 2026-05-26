import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel
from typing import List, Optional
from backend.app.database import get_db
from backend.app.models.prediction import StockPrediction
from backend.app.services.ai import async_client, gemini_client, types
from backend.app import config

logger = logging.getLogger("Chat")
logger.setLevel(logging.INFO)

router = APIRouter()

class ChatMessage(BaseModel):
    role: str  # "system", "user", "assistant"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    prediction_id: Optional[int] = None

def generate_synthetic_reply(messages: List[ChatMessage], prediction, symbol: str, support_str: str, resistance_str: str) -> str:
    """Generates a highly realistic, technical stock market response based on active asset parameters."""
    user_msg = messages[-1].content.lower() if messages else ""
    
    if "buy" in user_msg or "sell" in user_msg or "trade" in user_msg:
        if prediction:
            p_dict = prediction.to_dict()
            signal = p_dict['prediction_json'].get('signal', 'HOLD')
            try:
                current_val = float(p_dict['extracted_metrics']['current_value'])
            except Exception:
                current_val = 0.0
            
            rsi_val = p_dict['extracted_metrics']['indicators']['rsi']
            macd_trend = p_dict['extracted_metrics']['indicators']['macd_trend']
            return (
                f"Analyzing the active technical layout for {symbol}, our models suggest a "
                f"**{signal}** stance. The stock is currently consolidating near ${current_val:.2f} "
                f"with an RSI of {rsi_val} (MACD: *{macd_trend}*). "
                f"Executing a trade right here carries structural risks; wait for a clear breakout past resistance or pullbacks to key support bounds. "
                f"\n\n*Disclaimer: Aether models represent automated visual heuristics. Always conduct independent research before risking capital.*"
            )
        else:
            return "No active scan data is available yet. Please trigger an analysis run from the dashboard to initialize the trading stream."
            
    elif "support" in user_msg or "resistance" in user_msg or "level" in user_msg or "floor" in user_msg or "ceiling" in user_msg:
        if prediction:
            return (
                f"For {symbol}, key support floors are positioned at **{support_str}**, which has "
                f"historically seen buying accumulation. Overhead resistance ceilings are identified at **{resistance_str}**, "
                f"where sellers have previously capped dynamic breakout attempts. Breaking past these pivot boundaries is likely "
                f"to trigger a strong trend expansion."
            )
        else:
            return "Technical levels require an active screenshot prediction. Please trigger a scan to load support and resistance zones."
            
    elif "rsi" in user_msg or "macd" in user_msg or "indicator" in user_msg or "momentum" in user_msg:
        if prediction:
            p_dict = prediction.to_dict()
            rsi_val = p_dict['extracted_metrics']['indicators']['rsi']
            rsi_status = "Neutral" if 30 <= rsi_val <= 70 else ("Overbought" if rsi_val > 70 else "Oversold")
            macd_trend = p_dict['extracted_metrics']['indicators']['macd_trend']
            return (
                f"The momentum indicators for {symbol} currently register:\n"
                f"- **Relative Strength Index (RSI)**: {rsi_val} ({rsi_status} territory)\n"
                f"- **MACD Trend**: {macd_trend}\n\n"
                f"The current alignment indicates {p_dict['trend_direction'].lower()} continuation, with "
                f"MACD showing supportive structural convergence."
            )
        else:
            return "Indicator diagnostics require an active scan. Please execute a pipeline trigger first."
            
    else:
        if prediction:
            p_dict = prediction.to_dict()
            try:
                current_val = float(p_dict['extracted_metrics']['current_value'])
            except Exception:
                current_val = 0.0
            return (
                f"Hello! I am your Aether AI Trading Assistant. Looking at our latest scan for **{symbol}** (ID #{p_dict['id']}), "
                f"the price is hover-consolidating around ${current_val:.2f}. "
                f"Our Vision pipeline registers a **{p_dict['trend_direction']}** trend with **{p_dict['confidence_score']}% confidence**. "
                f"What specific details would you like me to unpack — supports/resistances, RSI dynamics, or interval projections?"
            )
        else:
            return "Hello! I am your Aether AI Trading Assistant. No historical predictions are loaded. Click the manual scan button to start!"

@router.post("/")
async def chat_with_ai(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Handles real-time conversation between the user and Aether AI, seeded with real technical indicators."""
    logger.info("📥 POST /api/chat request received.")
    try:
        # 1. Fetch prediction context from DB
        prediction = None
        if request.prediction_id:
            query = select(StockPrediction).where(StockPrediction.id == request.prediction_id)
            result = await db.execute(query)
            prediction = result.scalars().first()
        
        if not prediction:
            # Fallback to the latest prediction if no ID was provided or requested ID not found
            query = select(StockPrediction).order_by(StockPrediction.captured_at.desc()).limit(1)
            result = await db.execute(query)
            prediction = result.scalars().first()

        prediction_context = ""
        symbol = "the asset"
        support_str = "None"
        resistance_str = "None"
        
        if prediction:
            p_dict = prediction.to_dict()
            symbol = p_dict.get("stock_symbol", "the asset")
            
            # Safe extraction of support/resistance lists to string format
            supports = p_dict.get("support_levels") or []
            if isinstance(supports, (int, float)):
                supports = [supports]
            support_str = ", ".join([f"${float(s):.2f}" for s in supports]) if supports else "None"
            
            resistances = p_dict.get("resistance_levels") or []
            if isinstance(resistances, (int, float)):
                resistances = [resistances]
            resistance_str = ", ".join([f"${float(r):.2f}" for r in resistances]) if resistances else "None"
            
            try:
                current_val = float(p_dict['extracted_metrics']['current_value'])
            except Exception:
                current_val = 0.0
                
            prediction_context = f"""
CURRENT ASSET TECHNICAL CONTEXT:
- Asset Symbol: {symbol}
- Latest Scan ID: #{p_dict['id']}
- Captured Time: {p_dict['captured_at']}
- Current Estimated Value: ${current_val:.2f}
- Primary Trend: {p_dict['trend_direction']}
- Trading Signal: {p_dict['prediction_json'].get('signal', 'HOLD')}
- AI Confidence: {p_dict['confidence_score']}%
- Key Support Levels: {support_str}
- Key Resistance Levels: {resistance_str}
- Indicators: RSI is {p_dict['extracted_metrics']['indicators']['rsi']}, MACD Trend is {p_dict['extracted_metrics']['indicators']['macd_trend']}
- AI Summary Report: {p_dict['ai_summary']}
"""

        system_prompt = f"""You are the proprietary Aether Analytics AI Financial Intelligence Assistant.
You are chatting with a user about their stock graph analysis and predictions.
Use the following real-time asset context to answer their technical queries:
{prediction_context}

Guidelines:
1. Be professional, direct, objective, and analytical.
2. Incorporate specific price targets, support/resistance zones, and indicators (RSI, MACD) from the context.
3. If the user asks general financial questions, relate them back to the active asset screenshot details if possible.
4. Include a brief, professional warning/disclaimer that your outputs represent quantitative graph parsing, not financial advice, when asked about executing immediate trades.
5. If the user asks completely non-financial questions, politely guide them back to stock chart analysis."""

        # 2. Check for Mock Mode or missing API keys
        if config.IS_MOCK_MODE or (not async_client and not gemini_client):
            logger.info("🧠 [MOCK MODE] Generating synthetic financial chat response...")
            reply = generate_synthetic_reply(request.messages, prediction, symbol, support_str, resistance_str)
            return {
                "success": True,
                "reply": reply
            }

        # 3. Call AI API (Gemini Native or OpenAI/OpenRouter)
        try:
            if config.IS_GEMINI and gemini_client and types:
                logger.info("🧠 Dispatching chat query to Google GenAI (Gemini) native client...")
                contents = []
                for msg in request.messages:
                    # Gemini expects 'user' or 'model' roles
                    role = "user" if msg.role == "user" else "model"
                    contents.append(types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=msg.content)]
                    ))
                
                response = await gemini_client.aio.models.generate_content(
                    model=config.AI_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        max_output_tokens=600,
                        temperature=0.7
                    )
                )
                reply = response.text.strip()
                logger.info("✔️ Gemini chat response successfully compiled.")
            else:
                logger.info("🧠 Dispatching chat query to OpenAI reasoning pipeline...")
                openai_messages = [{"role": "system", "content": system_prompt}]
                for msg in request.messages:
                    openai_messages.append({"role": msg.role, "content": msg.content})

                response = await async_client.chat.completions.create(
                    model=config.AI_MODEL,
                    messages=openai_messages,
                    max_tokens=600,
                    temperature=0.7
                )
                
                reply = response.choices[0].message.content.strip()
                logger.info("✔️ OpenAI chat response successfully compiled.")
            
            return {
                "success": True,
                "reply": reply
            }
        except Exception as api_err:
            logger.warning(f"⚠️ AI completions failed: {api_err}. Falling back to high-fidelity synthetic chat simulator.")
            reply = generate_synthetic_reply(request.messages, prediction, symbol, support_str, resistance_str)
            return {
                "success": True,
                "reply": reply
            }

    except Exception as err:
        logger.error(f"❌ AI Chat endpoint failed: {err}")
        raise HTTPException(
            status_code=500,
            detail=f"Chatbot reasoning failure: {str(err)}"
        )
