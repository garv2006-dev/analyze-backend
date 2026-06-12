import logging
from typing import Optional
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw, ImageStat
from backend.app import config

logger = logging.getLogger("ChangeDetector")
logger.setLevel(logging.INFO)

def detect_and_highlight_changes(prev_path: str, curr_path: str, output_filename: str) -> Optional[str]:
    """
    Compares a previous screenshot with a current screenshot using block-based diffing.
    If changes are detected, highlights them with red bounding boxes and saves the result.
    Returns:
        str: Filename of the generated highlighted screenshot, or None if no significant change.
    """
    try:
        p_path = Path(prev_path)
        c_path = Path(curr_path)
        
        if not p_path.exists() or not c_path.exists():
            logger.warning(f"Screenshot files not found for change detection: '{prev_path}' or '{curr_path}'")
            return None
            
        img1 = Image.open(p_path).convert("RGB")
        img2 = Image.open(c_path).convert("RGB")
        
        # Ensure identical sizes
        if img1.size != img2.size:
            img1 = img1.resize(img2.size)
            
        width, height = img2.size
        highlighted = img2.copy()
        draw = ImageDraw.Draw(highlighted)
        
        block_size = 24 # 24x24 px block matching
        has_changes = False
        changed_blocks_count = 0
        total_blocks = 0
        
        for y in range(0, height, block_size):
            for x in range(0, width, block_size):
                total_blocks += 1
                box = (x, y, min(x + block_size, width), min(y + block_size, height))
                b1 = img1.crop(box)
                b2 = img2.crop(box)
                
                # Check mean pixel difference in RGB channels
                diff = ImageChops.difference(b1, b2)
                stat = ImageStat.Stat(diff)
                mean_diff = sum(stat.mean) / 3.0 # Average difference
                
                if mean_diff > 4.5: # Threshold for changes
                    draw.rectangle(box, outline=(255, 0, 0), width=1)
                    has_changes = True
                    changed_blocks_count += 1
                    
        # Filter out minor noise (e.g. cursor blinking or small timezone renders)
        percent_changed = (changed_blocks_count / total_blocks) * 100
        if has_changes and changed_blocks_count > 3:
            output_path = config.SCREENSHOTS_DIR / output_filename
            highlighted.save(output_path)
            logger.info(f"✔️ Visual changes detected ({percent_changed:.2f}% of grid). Saved: {output_filename}")
            return output_filename
            
        logger.info("No significant visual changes detected.")
        return None
        
    except Exception as e:
        logger.error(f"Error executing visual change detection: {e}")
        return None
