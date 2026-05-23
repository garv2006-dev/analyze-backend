import asyncio
import logging
import time
from pathlib import Path
from playwright.async_api import async_playwright
from backend.app import config

logger = logging.getLogger("Browser")
logger.setLevel(logging.INFO)

def _sync_capture_chart(target_url: str = None) -> dict:
    """Synchronous worker that executes the async playwright capture inside a ProactorEventLoop."""
    import sys
    
    if sys.platform == "win32":
        # Force ProactorEventLoopPolicy for this thread to support Playwright subprocesses
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_async_capture_chart_impl(target_url))
    finally:
        loop.close()

async def capture_chart(target_url: str = None) -> dict:
    """
    Main entry point for capturing a chart.
    Runs the capture in a separate thread using a ProactorEventLoop on Windows
    to prevent NotImplementedError under SelectorEventLoop (such as when Uvicorn is run with reload).
    """
    import sys
    
    # We only need to run in a separate thread on Windows where the current loop
    # might be a SelectorEventLoop. On other systems, we can run it directly.
    if sys.platform == "win32":
        logger.info("🔀 Running Playwright capture in a dedicated background thread with ProactorEventLoop...")
        return await asyncio.to_thread(_sync_capture_chart, target_url)
    else:
        return await _async_capture_chart_impl(target_url)

async def _async_capture_chart_impl(target_url: str = None) -> dict:

    """
    Launches headless Chromium to capture a clean screenshot of the stock index graph.
    Injects DOM operations to remove common overlays, ads, modals, headers, and sidebars.
    
    Returns:
        dict: Containing 'filename' and 'absolute_path'
    """
    logger.info("🌐 Initializing Playwright browser automation pipeline...")
    
    async with async_playwright() as p:
        browser = None
        try:
            # Launch chromium with secure flags and sandboxed operations
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-web-security"
                ]
            )
            
            # Create isolated browser context
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                device_scale_factor=1
            )
            
            page = await context.new_page()
            
            url_to_capture = target_url if target_url else config.TARGET_URL
            logger.info(f"🔗 Navigating to target stock URL: {url_to_capture}")
            # Dynamic navigation
            await page.goto(url_to_capture, wait_until="networkidle", timeout=35000)

            
            # Allow time for initial rendering
            logger.info(f"⏱ Waiting {config.RENDER_DELAY_MS}ms for chart animation frames...")
            await page.wait_for_timeout(config.RENDER_DELAY_MS)
            
            # Inject JavaScript to clean the screen (modals, popups, overlays, navbars, sidebars, ads)
            logger.info("🧹 Cleaning page DOM: Removing banners, login/signup modals, navbars and overlays...")
            await page.evaluate("""
                () => {
                    // 1. Detect and close standard modal dialogs
                    const closeSelectors = [
                        '.close-button', '.close-btn', '.close', '[aria-label="close"]', 
                        '[aria-label="Close"]', '.modal-close', '.popup-close', '.modal__close'
                    ];
                    
                    for (const sel of closeSelectors) {
                        try {
                            const btn = document.querySelector(sel);
                            if (btn && typeof btn.click === 'function') {
                                btn.click();
                                console.log('Dismissed modal via click:', sel);
                            }
                        } catch (e) {}
                    }
                    
                    // 2. Hide intrusive overlay/modal containers and ads
                    const hideSelectors = [
                        '[class*="modal"]', '[class*="popup"]', '[class*="overlay"]', '[class*="dialog"]',
                        '[id*="modal"]', '[id*="popup"]', '[id*="overlay"]', '[id*="dialog"]',
                        '.login-modal', '.signup-modal', '.modal-backdrop', '.fade.show',
                        'header', 'footer', 'nav', 'aside', '.sidebar', '#sidebar', '.header', '.footer', '.navbar',
                        '[class*="header"]', '[class*="footer"]', '[class*="navbar"]', '[class*="sidebar"]', 
                        '[class*="menu"]', '[class*="ad-"]', '[class*="ads-"]', '[id*="ad-"]', '[id*="ads-"]', 
                        '.ad-box', '.ad-container', '[class*="rodal"]'
                    ];
                    
                    document.querySelectorAll(hideSelectors.join(',')).forEach(el => {
                        try {
                            if (el && el.style) {
                                el.style.display = 'none';
                                el.style.opacity = '0';
                                el.style.pointerEvents = 'none';
                            }
                        } catch(e) {}
                    });
                    
                    // 3. Fix body overflow to allow normal screen rendering
                    document.body.style.overflow = 'auto';
                    document.documentElement.style.overflow = 'auto';
                }
            """)
            
            # Post DOM cleanup render buffer
            await page.wait_for_timeout(1000)
            
            timestamp = int(time.time() * 1000)
            filename = f"graph_{timestamp}.png"
            absolute_path = config.SCREENSHOTS_DIR / filename
            
            # Attempt clean high-res TradingView canvas download after switching to 5-minute interval
            downloaded_successfully = False
            
            try:
                logger.info("🔍 Locating TradingView chart iframe...")
                chart_frame = None
                for frame in page.frames:
                    if "tradingview" in frame.name or "tradingview" in frame.url:
                        chart_frame = frame
                        break
                
                if chart_frame:
                    logger.info(f"✔️ Found TradingView iframe: '{chart_frame.name}'")
                    
                    # 1. Switch to 5m interval
                    logger.info("⏱ Locating '5m' button to set 5-minute candlestick chart interval...")
                    five_m_loc = chart_frame.locator("text='5m'")
                    count = await five_m_loc.count()
                    clicked_5m = False
                    for i in range(count):
                        el = five_m_loc.nth(i)
                        if await el.is_visible():
                            logger.info(f"Clicking visible 5m button at index {i}...")
                            await el.click()
                            clicked_5m = True
                            break
                            
                    if not clicked_5m:
                        try:
                            await chart_frame.locator("div:text-is('5m')").click()
                            logger.info("Clicking 5m button via div text matching...")
                            clicked_5m = True
                        except Exception:
                            logger.warning("Could not click 5m button automatically.")
                            
                    # Wait for 5m chart candles to render
                    logger.info("⏱ Waiting 4000ms for 5-minute candlestick data to load...")
                    await page.wait_for_timeout(4000)
                    
                    # 2. Trigger direct chart download via the camera snapshot button
                    logger.info("📸 Locating TradingView camera snapshot button (#header-toolbar-screenshot)...")
                    camera_btn = chart_frame.locator("#header-toolbar-screenshot")
                    if await camera_btn.count() > 0 and await camera_btn.first.is_visible():
                        logger.info("Clicking snapshot camera icon to open download menu...")
                        await camera_btn.first.click()
                        await page.wait_for_timeout(1000) # wait for popover menu to render
                        
                        logger.info("Locating 'Download image' option in snapshot menu...")
                        download_option = chart_frame.locator("text='Download image'")
                        if await download_option.count() > 0 and await download_option.first.is_visible():
                            logger.info("Executing clean chart canvas download via browser interception...")
                            async with page.expect_download(timeout=15000) as download_info:
                                await download_option.first.click()
                            download = await download_info.value
                            await download.save_as(str(absolute_path))
                            logger.info(f"✔️ Clean high-resolution 5-minute chart image successfully downloaded: {absolute_path}")
                            downloaded_successfully = True
                        else:
                            logger.warning("'Download image' option not found or visible inside screenshot menu.")
                    else:
                        logger.warning("TradingView camera snapshot button not visible.")
                else:
                    logger.warning("TradingView iframe not found.")
            except Exception as tv_err:
                logger.error(f"⚠️ Error during TradingView frame interaction: {tv_err}")
                
            # Fallback to standard page screenshot if TradingView download failed
            if not downloaded_successfully:
                logger.info("⚠️ Direct download failed. Falling back to screenshot capture method...")
                
                # Determine elements to crop screenshot to
                # We want ONLY the graph, so let's try to find target_selector or the largest canvas
                logger.info("📸 Evaluating graph canvas boundaries...")
                
                # First, check if custom selector exists and is not body
                has_custom_selector = config.TARGET_SELECTOR and config.TARGET_SELECTOR != "body"
                
                bounding_box = None
                target_locator = None
                
                if has_custom_selector:
                    try:
                        logger.info(f"Targeting specified selector: {config.TARGET_SELECTOR}")
                        locator = page.locator(config.TARGET_SELECTOR).first
                        if await locator.is_visible():
                            target_locator = locator
                    except Exception as e:
                        logger.warning(f"Failed resolving selector locator: {e}")
                
                # If no target locator yet, let's scan for standard chart canvases (TradingView lightweight charts, etc.)
                if not target_locator:
                    try:
                        # Let's see if we have canvas elements or TV lightweight classes
                        tv_selector = ".tv-lightweight-charts, canvas, .chart-container, #chart-container"
                        locators = page.locator(tv_selector)
                        count = await locators.count()
                        
                        if count > 0:
                            logger.info(f"Found {count} candidate chart/canvas element(s). Locating main canvas...")
                            # Pick the one with the largest area to capture
                            max_area = 0
                            best_locator = None
                            
                            for i in range(count):
                                loc = locators.nth(i)
                                if await loc.is_visible():
                                    box = await loc.bounding_box()
                                    if box:
                                        area = box["width"] * box["height"]
                                        if area > max_area:
                                            max_area = area
                                            best_locator = loc
                                            
                            if best_locator and max_area > 10000: # reasonable size threshold
                                target_locator = best_locator
                                logger.info(f"Found largest chart canvas with area {max_area}px.")
                    except Exception as e:
                        logger.warning(f"Error scanning for largest canvas: {e}")
                
                # Screenshot taking
                if target_locator:
                    try:
                        logger.info("Taking precision cropped screenshot of the chart container...")
                        await target_locator.screenshot(path=str(absolute_path))
                        logger.info(f"✔️ Precision chart screenshot captured and saved: {absolute_path}")
                    except Exception as locator_err:
                        logger.warning(f"Failed precision locator screenshot: {locator_err}. Falling back to page screenshot.")
                        await page.screenshot(path=str(absolute_path))
                        logger.info(f"✔️ Fallback page viewport screenshot captured: {absolute_path}")
                else:
                    logger.info("No explicit chart canvas found. Taking full-page screenshot.")
                    await page.screenshot(path=str(absolute_path), full_page=True)
                    logger.info(f"✔️ Full page screenshot captured and saved: {absolute_path}")
                
            # Prune old screenshots to prevent disk leak
            await prune_old_screenshots()
            
            return {
                "filename": filename,
                "absolute_path": str(absolute_path)
            }
            
        except Exception as err:
            logger.error(f"❌ Playwright pipeline failed: {err}")
            raise RuntimeError(f"Browser automation failed: {err}")
            
        finally:
            if browser:
                await browser.close()
                logger.info("🔒 Headless browser context torn down successfully.")

async def prune_old_screenshots():
    """Prunes screenshots older than 24 hours to prevent storage bloating."""
    logger.info("🧹 Running background screenshot pruning routine...")
    try:
        now = time.time()
        threshold_seconds = 24 * 60 * 60 # 24 hours
        pruned_count = 0
        
        for file_path in config.SCREENSHOTS_DIR.glob("graph_*.png"):
            try:
                mtime = file_path.stat().st_mtime
                age_seconds = now - mtime
                if age_seconds > threshold_seconds:
                    file_path.unlink()
                    pruned_count += 1
            except Exception as e:
                logger.error(f"Failed to stat/unlink file {file_path.name}: {e}")
                
        if pruned_count > 0:
            logger.info(f"🧹 Storage cleanup completed: Deleted {pruned_count} obsolete screenshot(s) older than 24h.")
    except Exception as err:
        logger.error(f"Error during file pruning cleanup: {err}")
