import logging
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from backend.app.database import get_db
from backend.app.models.prediction import StockPrediction
from backend.app.models.hidden_prediction import HiddenPrediction
from backend.app.automation.scheduler import execute_analysis_cycle, get_saved_interval, update_scheduler_interval

logger = logging.getLogger("Routes")
logger.setLevel(logging.INFO)

router = APIRouter()

class TriggerRequest(BaseModel):
    target_url: Optional[str] = None
    stock_symbol: Optional[str] = None


from typing import Optional
from sqlalchemy import func
from backend.app import config

@router.get("/")
async def get_predictions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    limit: Optional[int] = Query(default=None, ge=1, le=100),
    symbol: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db)
):
    """Fetches paginated list of historical stock graph predictions, ordered descending by capture time, optionally filtered by symbol."""
    logger.info(f"📥 GET /api/predictions?page={page}&page_size={page_size}&limit={limit}&symbol={symbol} request received.")
    try:
        from datetime import datetime, timezone
        
        # Build counting query
        count_query = select(func.count()).select_from(StockPrediction)
        count_query = count_query.where(StockPrediction.id.not_in(select(HiddenPrediction.prediction_id)))
        if symbol and symbol.upper() != 'ALL':
            count_query = count_query.where(StockPrediction.stock_symbol == symbol.upper())
            
        count_result = await db.execute(count_query)
        total = count_result.scalar()

        if limit is not None:
            # Maintain backward compatibility if limit parameter is explicitly passed
            query = select(StockPrediction).where(StockPrediction.id.not_in(select(HiddenPrediction.prediction_id))).order_by(StockPrediction.captured_at.desc())
            if symbol and symbol.upper() != 'ALL':
                query = query.where(StockPrediction.stock_symbol == symbol.upper())
            query = query.limit(limit)
            active_page_size = limit
        else:
            offset = (page - 1) * page_size
            query = select(StockPrediction).where(StockPrediction.id.not_in(select(HiddenPrediction.prediction_id))).order_by(StockPrediction.captured_at.desc())
            if symbol and symbol.upper() != 'ALL':
                query = query.where(StockPrediction.stock_symbol == symbol.upper())
            query = query.offset(offset).limit(page_size)
            active_page_size = page_size

        result = await db.execute(query)
        rows = result.scalars().all()
        
        # Serialize and return
        data = [row.to_dict() for row in rows]
        
        return {
            "success": True,
            "count": len(data),
            "total": total,
            "page": page if limit is None else 1,
            "page_size": active_page_size,
            "data": data
        }
    except Exception as error:
        logger.error(f"Failed to retrieve predictions: {error}")
        raise HTTPException(
            status_code=500,
            detail="Severe database disruption occurred while retrieving prediction logs."
        )


class SchedulerSettingsRequest(BaseModel):
    interval_minutes: int
    only_during_market_hours: Optional[bool] = None
    market_start_time: Optional[str] = None
    market_end_time: Optional[str] = None
    exclude_weekends: Optional[bool] = None

@router.get("/scheduler-settings")
async def get_scheduler_settings():
    """Gets the current background scheduler settings dictionary."""
    logger.info("📥 GET /api/predictions/scheduler-settings request received.")
    try:
        from backend.app.automation.scheduler import get_saved_settings
        settings = get_saved_settings()
        return {
            "success": True,
            **settings
        }
    except Exception as e:
        logger.error(f"Failed to get scheduler settings: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve background scheduler settings."
        )

@router.post("/scheduler-settings")
async def update_scheduler_settings(settings: SchedulerSettingsRequest):
    """Updates the background scheduler settings dynamically"""
    logger.info(f"📥 POST /api/predictions/scheduler-settings request received.")
    if settings.interval_minutes < 1:
        raise HTTPException(
            status_code=400,
            detail="Interval must be at least 1 minute."
        )
    try:
        from backend.app.automation.scheduler import update_scheduler_settings_dict
        
        payload = {"interval_minutes": settings.interval_minutes}
        if settings.only_during_market_hours is not None:
            payload["only_during_market_hours"] = settings.only_during_market_hours
        if settings.market_start_time is not None:
            payload["market_start_time"] = settings.market_start_time
        if settings.market_end_time is not None:
            payload["market_end_time"] = settings.market_end_time
        if settings.exclude_weekends is not None:
            payload["exclude_weekends"] = settings.exclude_weekends
            
        success = update_scheduler_settings_dict(payload)
        if success:
            return {
                "success": True,
                "message": "Background scheduler settings successfully updated.",
                **payload
            }
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to reschedule the background cron job."
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update scheduler settings: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while updating the background scheduler: {str(e)}"
        )

@router.delete("/{id}")
async def delete_prediction(id: int, db: AsyncSession = Depends(get_db)):
    """Deletes a single prediction record by ID, including its associated screenshots file."""
    logger.info(f"📥 DELETE /api/predictions/{id} request received.")
    try:
        query = select(StockPrediction).where(StockPrediction.id == id)
        result = await db.execute(query)
        row = result.scalars().first()
        
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Prediction record with ID #{id} was not found."
            )
            
        # Check if already hidden to prevent duplicates
        check_query = select(HiddenPrediction).where(HiddenPrediction.prediction_id == id)
        check_result = await db.execute(check_query)
        if not check_result.scalars().first():
            hidden_pred = HiddenPrediction(prediction_id=id)
            db.add(hidden_pred)
            await db.commit()
        
        return {
            "success": True,
            "message": f"Prediction record #{id} has been hidden from the dashboard."
        }
    except HTTPException:
        raise
    except Exception as error:
        await db.rollback()
        logger.error(f"Failed to delete prediction record #{id}: {error}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while deleting the prediction record."
        )

@router.get("/latest")
async def get_latest_prediction(db: AsyncSession = Depends(get_db)):
    """Retrieves the single most recently executed stock prediction analysis."""
    logger.info("📥 GET /api/predictions/latest request received.")
    try:
        query = select(StockPrediction).order_by(StockPrediction.captured_at.desc()).limit(1)
        result = await db.execute(query)
        row = result.scalars().first()
        
        return {
            "success": True,
            "data": row.to_dict() if row else None
        }
    except Exception as error:
        logger.error(f"Failed to retrieve latest prediction: {error}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve latest prediction."
        )

@router.get("/{id}")
async def get_prediction_by_id(id: int, db: AsyncSession = Depends(get_db)):
    """Fetches a single detailed prediction analysis by its primary key identifier."""
    logger.info(f"📥 GET /api/predictions/{id} request received.")
    try:
        query = select(StockPrediction).where(StockPrediction.id == id)
        result = await db.execute(query)
        row = result.scalars().first()
        
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Prediction record with ID #{id} was not found."
            )
            
        return {
            "success": True,
            "data": row.to_dict()
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Failed to retrieve prediction by ID: {error}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while fetching the detailed prediction record."
        )

@router.post("/trigger")
async def trigger_manual_analysis(request_data: Optional[TriggerRequest] = None, db: AsyncSession = Depends(get_db)):
    """Manually forces an immediate Playwright capture and OpenAI Vision analysis sequence, saving the results."""
    logger.info("📥 POST /api/predictions/trigger request received. Initiating immediate automated run...")
    try:
        target_url = request_data.target_url if request_data else None
        stock_symbol = request_data.stock_symbol if (request_data and request_data.stock_symbol) else "NIFTY50"
        
        # Run core cycle using current db session
        prediction = await execute_analysis_cycle(db, stock_symbol=stock_symbol, target_url=target_url)
        await db.commit()

        
        return {
            "success": True,
            "data": prediction.to_dict()
        }
    except Exception as error:
        await db.rollback()
        logger.error(f"Manual scan cycle failed: {error}")
        raise HTTPException(
            status_code=500,
            detail=f"On-demand browser capture/AI analysis cycle failed: {error}"
        )


@router.post("/trigger-all")
async def trigger_all_assets():
    """
    Runs the full capture + AI analysis pipeline for ALL saved watchlist assets sequentially.
    Returns a per-asset results summary with individual success/failure status.
    """
    logger.info("📥 POST /api/predictions/trigger-all request received.")
    from backend.app.models.saved_asset import SavedAsset
    from backend.app import database as db_module
    from sqlalchemy.future import select as sa_select

    # Load all saved assets
    assets_to_run = []
    try:
        async with db_module.SessionLocal() as db:
            result = await db.execute(sa_select(SavedAsset).order_by(SavedAsset.created_at.asc()))
            rows = result.scalars().all()
            assets_to_run = [(row.symbol, row.url) for row in rows]
    except Exception as load_err:
        logger.error(f"Failed to load saved assets: {load_err}")

    if not assets_to_run:
        from backend.app import config as app_config
        assets_to_run = [("NIFTY50", app_config.TARGET_URL)]

    total = len(assets_to_run)
    logger.info(f"🚀 trigger-all: Running analysis for {total} asset(s): {[s for s, _ in assets_to_run]}")

    results = []
    for idx, (symbol, url) in enumerate(assets_to_run, 1):
        logger.info(f"🚀 trigger-all [{idx}/{total}]: Analyzing {symbol}...")
        async with db_module.SessionLocal() as session:
            try:
                prediction = await execute_analysis_cycle(session, stock_symbol=symbol, target_url=url)
                await session.commit()
                results.append({"symbol": symbol, "success": True, "id": prediction.id})
                logger.info(f"✔️ trigger-all [{idx}/{total}]: {symbol} → ID #{prediction.id}")
            except Exception as err:
                await session.rollback()
                logger.error(f"❌ trigger-all [{idx}/{total}]: {symbol} failed — {err}")
                results.append({"symbol": symbol, "success": False, "error": str(err)})

        # Delay between assets to respect API rate limits (important for Gemini free tier: 15 RPM)
        if idx < total:
            import asyncio as _asyncio
            await _asyncio.sleep(8)

    success_count = sum(1 for r in results if r["success"])
    return {
        "success": True,
        "total": total,
        "completed": success_count,
        "results": results
    }


class BulkDeleteRequest(BaseModel):
    ids: list[int] = []
    delete_all: bool = False

@router.post("/bulk-delete")
async def bulk_delete_predictions(request_data: BulkDeleteRequest, db: AsyncSession = Depends(get_db)):
    """Hides multiple prediction records by adding them to the hidden_predictions table."""
    logger.info(f"📥 POST /api/predictions/bulk-delete request received. (delete_all={request_data.delete_all})")
    try:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from backend.app.database import is_fallback_mode

        if request_data.delete_all:
            # Find all prediction IDs that are not already hidden
            query = select(StockPrediction.id).where(StockPrediction.id.not_in(select(HiddenPrediction.prediction_id)))
            result = await db.execute(query)
            ids_to_hide = result.scalars().all()
        else:
            ids_to_hide = request_data.ids
            
        if not ids_to_hide:
            return {"success": True, "message": "No logs to hide."}

        # Add all IDs to the HiddenPrediction table
        hidden_objects = [{"prediction_id": pid} for pid in ids_to_hide]
        
        # Use simple iterative insert and ignore unique constraint errors to be dialect-agnostic
        for pid in ids_to_hide:
            check_query = select(HiddenPrediction).where(HiddenPrediction.prediction_id == pid)
            check_result = await db.execute(check_query)
            if not check_result.scalars().first():
                db.add(HiddenPrediction(prediction_id=pid))

        await db.commit()
        
        return {
            "success": True,
            "message": f"Successfully hidden {len(ids_to_hide)} prediction records from the dashboard."
        }
    except Exception as error:
        await db.rollback()
        logger.error(f"Failed to bulk hide prediction records: {error}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while bulk hiding prediction records."
        )
