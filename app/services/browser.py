import asyncio
import logging
import os
import time
from pathlib import Path

# Prevent Playwright screenshots from hanging/timing out while waiting for fonts to load
os.environ["PW_TEST_SCREENSHOT_NO_FONTS_READY"] = "1"

from playwright.async_api import async_playwright
from backend.app import config

logger = logging.getLogger("Browser")
logger.setLevel(logging.INFO)

def _is_image_blank(image_path: Path) -> bool:
    """
    Checks if the screenshot is blank/single-color (mostly pure white).
    Returns True if the image is blank, False otherwise.
    """
    try:
        from PIL import Image
        if not image_path.exists():
            return True
        with Image.open(image_path) as img:
            rgb_img = img.convert("RGB")
            colors = rgb_img.getcolors(maxcolors=2)
            if colors and len(colors) <= 1:
                return True
                
            # Convert to Grayscale to count pixels matching white background
            gray_img = img.convert("L")
            extrema = gray_img.getextrema()
            if extrema and extrema[0] == extrema[1]:
                return True
                
            # Histogram check: if 99.9% of pixels are white (>= 250 brightness)
            hist = gray_img.histogram()
            total_pixels = gray_img.width * gray_img.height
            if total_pixels > 0:
                white_pixels = sum(hist[250:])
                if (white_pixels / total_pixels) > 0.999:
                    return True
    except Exception as e:
        logger.warning(f"Failed to check screenshot blankness: {e}")
    return False

def _sync_capture_chart(target_url: str = None, stock_symbol: str = None) -> dict:
    """Synchronous worker that executes the async playwright capture inside a ProactorEventLoop."""
    import sys
    
    if sys.platform == "win32":
        # Force ProactorEventLoopPolicy for this thread to support Playwright subprocesses
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_async_capture_chart_impl(target_url, stock_symbol))
    finally:
        loop.close()

async def capture_chart(target_url: str = None, stock_symbol: str = None) -> dict:
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
        return await asyncio.to_thread(_sync_capture_chart, target_url, stock_symbol)
    else:
        return await _async_capture_chart_impl(target_url, stock_symbol)

async def _async_capture_chart_impl(target_url: str = None, stock_symbol: str = None) -> dict:
    """
    Launches headless Chromium to capture a clean screenshot of the stock index graph.
    Injects DOM operations to remove common overlays, ads, modals, headers, and sidebars.
    If the screenshot is blank/white, it reloads the page and retries up to 3 times
    with progressive wait delays.
    
    Returns:
        dict: Containing 'filename' and 'absolute_path'
    """
    logger.info("🌐 Initializing Playwright browser automation pipeline...")
    
    max_attempts = 3
    attempt = 1
    
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
            
            # Create isolated browser context with custom user agent to avoid bot-detection empty pages
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                device_scale_factor=1,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            page = await context.new_page()
            
            # Font blocking route removed as it triggers blank screenshots in headless mode

            
            url_to_capture = target_url if target_url else config.TARGET_URL
            
            filename = None
            absolute_path = None
            extracted_price = None
            
            while attempt <= max_attempts:
                logger.info(f"🔄 [Attempt {attempt}/{max_attempts}] Navigating to target stock URL: {url_to_capture}")
                try:
                    if attempt > 1:
                        logger.info("Refreshing the page to recover from blank render...")
                        await page.reload(wait_until="domcontentloaded", timeout=20000)
                    else:
                        await page.goto(url_to_capture, wait_until="domcontentloaded", timeout=20000)
                    logger.info("✔️ Page load completed successfully (domcontentloaded).")
                except Exception as goto_err:
                    logger.warning(f"⚠️ page.goto/reload timed out or failed: {goto_err}. Attempting to proceed...")

                # Guarantee body element exists before running DOM operations
                try:
                    await page.wait_for_selector("body", state="attached", timeout=10000)
                except Exception as body_err:
                    logger.warning(f"⚠️ Body element check timed out: {body_err}")

                # Progressive render wait loop on the SAME page load
                # This gives the React bundle/Chart library time to fetch data and render, 
                # avoiding expensive page reloads if it is just a slow network/API response.
                check_loop = 1
                max_checks = 3
                captured_valid = False
                
                while check_loop <= max_checks:
                    # Determine wait time: check 1 (2s), check 2 (4s), check 3 (8s)
                    wait_time = config.RENDER_DELAY_MS * (2 ** (check_loop - 1))
                    logger.info(f"⏱ [Check {check_loop}/{max_checks}] Waiting {wait_time}ms for chart animation frames to render...")
                    await page.wait_for_timeout(wait_time)
                    
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
                                    }
                                } catch (e) {}
                            }
                            
                            // 2. Hide intrusive overlay/modal containers and ads safely
                            const hideSelectors = [
                                'header', 'footer', 'nav', 'aside', 
                                '#header', '.header', '#footer', '.footer', '#navbar', '.navbar', '#sidebar', '.sidebar',
                                '.login-modal', '.signup-modal', '.modal-backdrop', '.fade.show',
                                '.ad-box', '.ad-container', '[class*="rodal"]',
                                '[class*="ad-"]', '[class*="ads-"]', '[id*="ad-"]', '[id*="ads-"]'
                            ];
                            
                            document.querySelectorAll(hideSelectors.join(',')).forEach(el => {
                                try {
                                    if (el && el.tagName !== 'BODY' && el.tagName !== 'HTML' && el.style) {
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
                            
                            try:
                                # Switch to 5m interval
                                logger.info("⏱ Locating '5m' button to set 5-minute candlestick chart interval...")
                                five_m_loc = chart_frame.locator("text='5m'")
                                count = await five_m_loc.count()
                                clicked_5m = False
                                for i in range(count):
                                    el = five_m_loc.nth(i)
                                    try:
                                        if await el.is_visible():
                                            await el.click(timeout=2000)
                                            clicked_5m = True
                                            break
                                    except Exception:
                                        pass
                                        
                                if not clicked_5m:
                                    try:
                                        # Use .first to prevent strict mode violations (since multiple divs can match '5m')
                                        await chart_frame.locator("div:text-is('5m')").first.click(timeout=2000)
                                        clicked_5m = True
                                    except Exception:
                                        pass
                                        
                                if clicked_5m:
                                    logger.info("✔️ Successfully set chart interval to 5m.")
                                else:
                                    logger.info("ℹ️ 5m button click bypassed (already active or hidden).")
                            except Exception as tv_interval_err:
                                logger.info(f"ℹ️ 5m button interval selection bypassed: {tv_interval_err}")
                                    
                            # Wait for 5m chart candles to render
                            logger.info("⏱ Waiting 4000ms for 5-minute candlestick data to load...")
                            await page.wait_for_timeout(4000)
                            
                            # Clean DOM inside the iframe to remove overlays blocking clicks
                            try:
                                await chart_frame.evaluate("""
                                    () => {
                                        const hideSelectors = [
                                            '.rodal-mask', '.rodal', '[class*="rodal"]', '.modal-backdrop', '.fade.show'
                                        ];
                                        document.querySelectorAll(hideSelectors.join(',')).forEach(el => {
                                            if (el && el.style) {
                                                el.style.display = 'none';
                                            }
                                        });
                                    }
                                """)
                            except Exception:
                                pass

                            # Trigger direct chart download via the camera snapshot button
                            logger.info("📸 Locating TradingView camera snapshot button (#header-toolbar-screenshot)...")
                            camera_btn = chart_frame.locator("#header-toolbar-screenshot")
                            if await camera_btn.count() > 0 and await camera_btn.first.is_visible():
                                await camera_btn.first.click(timeout=3000)
                                await page.wait_for_timeout(1000)
                                
                                download_option = chart_frame.locator("text='Download image'")
                                if await download_option.count() > 0 and await download_option.first.is_visible():
                                    async with page.expect_download(timeout=10000) as download_info:
                                        await download_option.first.click(timeout=3000)
                                    download = await download_info.value
                                    await download.save_as(str(absolute_path))
                                    downloaded_successfully = True
                    except Exception as tv_err:
                        # Log simple message without polluting terminal with playwright stack trace
                        logger.info(f"ℹ️ TradingView direct snapshot interaction bypassed: {tv_err}")
                        
                    # Fallback to standard page screenshot if TradingView download failed
                    if not downloaded_successfully:
                        logger.info("⚠️ Direct download failed. Falling back to screenshot capture method...")
                        
                        # Determine elements to crop screenshot to
                        logger.info("📸 Evaluating graph canvas boundaries...")
                        
                        has_custom_selector = config.TARGET_SELECTOR and config.TARGET_SELECTOR != "body"
                        target_locator = None
                        
                        if has_custom_selector:
                            try:
                                locator = page.locator(config.TARGET_SELECTOR).first
                                if await locator.is_visible():
                                    target_locator = locator
                            except Exception:
                                pass
                        
                        # Scan for standard chart canvases
                        if not target_locator:
                            try:
                                tv_selector = ".tv-lightweight-charts, canvas, .chart-container, #chart-container"
                                locators = page.locator(tv_selector)
                                count = await locators.count()
                                
                                if count > 0:
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
                                                    
                                    if best_locator and max_area > 10000:
                                        target_locator = best_locator
                            except Exception:
                                pass
                        
                        # Screenshot taking
                        if target_locator:
                            try:
                                await target_locator.screenshot(path=str(absolute_path), timeout=15000)
                                logger.info(f"✔️ Precision chart screenshot captured: {absolute_path}")
                            except Exception:
                                await page.screenshot(path=str(absolute_path), timeout=15000)
                        else:
                            await page.screenshot(path=str(absolute_path), full_page=True, timeout=15000)
                    
                    # Verify screenshot blankness/white screen
                    if _is_image_blank(absolute_path):
                        logger.warning(f"⚠️ Screenshot {filename} is blank/white. Deleting file...")
                        try:
                            absolute_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                        # Move to next check loop on same page
                        check_loop += 1
                    else:
                        logger.info(f"✔️ Valid screenshot captured on check {check_loop} of attempt {attempt}.")
                        captured_valid = True
                        break
                
                if captured_valid:
                    break
                else:
                    logger.warning(f"⚠️ Page stayed blank after {max_checks} rendering wait cycles on attempt {attempt}. Triggering page reload...")
                    attempt += 1
            
            if attempt > max_attempts:
                raise RuntimeError(f"Failed to capture non-blank screenshot after {max_attempts} attempts.")
                
            # Prune old screenshots to prevent disk leak
            await prune_old_screenshots()
            
            return {
                "filename": filename,
                "absolute_path": str(absolute_path),
                "extracted_price": extracted_price
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
