import logging
import re
import cloudinary
# pyrefly: ignore [missing-import]
import cloudinary.uploader
from backend.app import config

logger = logging.getLogger("Cloudinary")
logger.setLevel(logging.INFO)

# Initialize Cloudinary if credentials are configured
if config.IS_CLOUDINARY_ENABLED:
    try:
        cloudinary.config(
            cloud_name=config.CLOUDINARY_CLOUD_NAME,
            api_key=config.CLOUDINARY_API_KEY,
            api_secret=config.CLOUDINARY_API_SECRET,
            secure=True
        )
        logger.info("☁️ Cloudinary successfully initialized.")
    except Exception as init_err:
        logger.error(f"❌ Failed to initialize Cloudinary client: {init_err}")
else:
    logger.warning("⚠️ Cloudinary credentials are not fully configured. Falling back to local storage.")

def upload_image(file_path: str, public_id: str = None) -> str:
    """
    Uploads a local image to Cloudinary and returns its secure URL.
    If Cloudinary is disabled, returns None.
    
    This is a synchronous network call and should be executed inside asyncio.to_thread in async paths.
    """
    if not config.IS_CLOUDINARY_ENABLED:
        logger.warning("Cloudinary upload bypassed (credentials missing).")
        return None
        
    try:
        logger.info(f"📤 Uploading '{file_path}' to Cloudinary...")
        options = {
            "folder": "ai_graph_analyzer",
            "overwrite": True,
            "resource_type": "image"
        }
        if public_id:
            options["public_id"] = public_id
            
        result = cloudinary.uploader.upload(file_path, **options)
        secure_url = result.get("secure_url")
        logger.info(f"✔️ Image successfully uploaded to Cloudinary: {secure_url}")
        return secure_url
    except Exception as e:
        logger.error(f"❌ Failed to upload image to Cloudinary: {e}")
        raise

def delete_image(image_url: str) -> bool:
    """
    Parses the public ID from the Cloudinary URL and deletes it from Cloudinary.
    Returns True if successful, False otherwise.
    
    This is a synchronous network call and should be executed inside asyncio.to_thread in async paths.
    """
    if not config.IS_CLOUDINARY_ENABLED:
        logger.warning("Cloudinary delete bypassed (credentials missing).")
        return False
        
    try:
        # Extract public ID from Cloudinary URL
        # Standard format: https://res.cloudinary.com/{cloud_name}/image/upload/{options}/{public_id}.{format}
        # Example: https://res.cloudinary.com/dnnx2sedu/image/upload/v1716480000/ai_graph_analyzer/graph_1716480000000.png
        match = re.search(r"/image/upload/(?:v\d+/)?(.+?)(?:\.[a-z0-9]+)?$", image_url)
        if not match:
            logger.warning(f"Could not parse Cloudinary public ID from URL: {image_url}")
            return False
            
        public_id = match.group(1)
        logger.info(f"🗑️ Deleting public ID '{public_id}' from Cloudinary...")
        
        result = cloudinary.uploader.destroy(public_id)
        if result.get("result") == "ok":
            logger.info(f"✔️ Image '{public_id}' successfully deleted from Cloudinary.")
            return True
        else:
            logger.warning(f"Cloudinary destroy response was not 'ok': {result}")
            return False
    except Exception as e:
        logger.error(f"❌ Failed to delete image from Cloudinary: {e}")
        return False
