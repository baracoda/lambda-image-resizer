"""
Lambda Image Resizer
--------------------
Resizes images on-demand for CloudFront/S3, using _original images as source.
Supports local (mock) and live (production) execution modes.
"""

import os
import boto3
import io
import logging
from PIL import Image
from urllib.parse import parse_qs, urlparse, unquote
import base64

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
DEFAULT_MAX_DIMENSION = 2000  # Prevent abuse

class ImageResizerError(Exception):
    """Base exception for image resizer errors."""
    pass

class S3KeyNotFoundError(ImageResizerError):
    """Raised when an S3 key is not found."""
    pass

class S3OperationError(ImageResizerError):
    """Raised for general S3 operation errors."""
    pass

class ImageProcessingError(ImageResizerError):
    """Raised for errors during image processing."""
    pass

def lambda_handler(event, context):
    """
    AWS Lambda handler to resize images on-demand and serve via S3.
    Expects event['queryStringParameters'] to contain 'w' and 'h'.
    Reads all configuration from environment variables.
    """
    # Read environment variables
    bucket = os.environ.get('IMAGE_BUCKET')
    s3_prefix = os.environ.get('S3_PREFIX', '')
    max_dimension = int(os.environ.get('MAX_DIMENSION', DEFAULT_MAX_DIMENSION))
    execution_mode = os.environ.get('EXECUTION_MODE', 'live').lower()

    if not bucket:
        logger.error('IMAGE_BUCKET environment variable not set.')
        return error_response(500, 'IMAGE_BUCKET environment variable not set.', error_type='ConfigError')

    if execution_mode == 'local':
        logger.info('Running in LOCAL execution mode. Mocks or local configs can be set up here.')
    else:
        logger.info('Running in LIVE execution mode.')

    # Create S3 client at runtime (important for tests with moto)
    s3 = boto3.client('s3')

    try:
        # Parse request
        path, width, height = parse_request(event, max_dimension)
        logger.info(f"Requested: {path} at {width}x{height}")

        # Validate extension
        ext = os.path.splitext(path)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            logger.warning(f"Unsupported file type requested: {ext}")
            return error_response(400, 'Unsupported file type. Allowed: .jpg, .jpeg, .png, .webp', error_type='ValidationError')

        # Build S3 key for resized and original image
        base, ext = os.path.splitext(path)
        if s3_prefix and not base.startswith(s3_prefix):
            base = f"{s3_prefix.rstrip('/')}/{base.lstrip('/')}"
        resized_key = f"{base}_{width}_{height}{ext}"
        original_key = f"{base}_original{ext}"

        # 1. Check if resized image exists
        try:
            if s3_key_exists(s3, bucket, resized_key):
                logger.info(f"Resized image exists: {resized_key}")
                return s3_image_response(s3, bucket, resized_key, ext)
        except S3OperationError as e:
            logger.error(f"S3 error while checking resized image: {e}")
            return error_response(500, str(e), error_type='S3Error')

        # 2. If not, fetch _original
        try:
            if not s3_key_exists(s3, bucket, original_key):
                logger.warning(f"Original image not found: {original_key}")
                return error_response(404, 'Original image not found. Please upload the _original image.', error_type='NotFound')
            orig_img_bytes = get_s3_object(s3, bucket, original_key)
        except S3KeyNotFoundError:
            logger.warning(f"Original image not found: {original_key}")
            return error_response(404, 'Original image not found. Please upload the _original image.', error_type='NotFound')
        except S3OperationError as e:
            logger.error(f"S3 error while fetching original image: {e}")
            return error_response(500, str(e), error_type='S3Error')

        # 3. Resize
        try:
            resized_img_bytes = resize_image(orig_img_bytes, width, height, ext)
        except ImageProcessingError as e:
            logger.error(f"Image processing error: {e}")
            return error_response(500, str(e), error_type='ImageProcessingError')
        except Exception as e:
            logger.error(f"Unexpected error during image processing: {e}")
            return error_response(500, 'Failed to process image.', error_type='ImageProcessingError')

        # 4. Store resized image
        try:
            put_s3_object(s3, bucket, resized_key, resized_img_bytes, ext)
        except S3OperationError as e:
            logger.error(f"S3 error while storing resized image: {e}")
            return error_response(500, str(e), error_type='S3Error')

        # 5. Return resized image
        return image_response(resized_img_bytes, ext)

    except ValueError as ve:
        logger.warning(f"Input validation error: {ve}")
        return error_response(400, str(ve), error_type='ValidationError')
    except Exception as e:
        logger.exception("Unhandled error processing image request")
        return error_response(500, f"Internal error: {str(e)}", error_type='InternalError')

def parse_request(event, max_dimension):
    """
    Extracts image path, width, and height from the event.
    Validates and returns (path, width, height).
    """
    # For Lambda@Edge, path is in event['Records'][0]['cf']['request']['uri']
    # For API Gateway, path is in event['path']
    if 'Records' in event:
        # Lambda@Edge
        cf_req = event['Records'][0]['cf']['request']
        path = unquote(cf_req['uri'].lstrip('/'))
        qs = parse_qs(cf_req.get('querystring', ''))
    else:
        # API Gateway
        path = unquote(event.get('path', '').lstrip('/'))
        qs = event.get('queryStringParameters', {})
    
    # Get width and height
    w = qs.get('w')
    h = qs.get('h')
    if isinstance(w, list):
        w = w[0]
    if isinstance(h, list):
        h = h[0]
    try:
        width = int(w)
        height = int(h)
        if not (1 <= width <= max_dimension and 1 <= height <= max_dimension):
            raise ValueError(f'Width and height must be between 1 and {max_dimension}.')
    except Exception:
        raise ValueError('Invalid width or height. Please provide integer values within allowed range.')
    return path, width, height

def s3_key_exists(s3, bucket, key):
    """
    Check if a key exists in the specified S3 bucket.
    Returns True if exists, False if not.
    Raises S3OperationError for other S3 errors.
    """
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except s3.exceptions.ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            return False
        raise S3OperationError(f"S3 error checking key '{key}': {e}")
    except Exception as e:
        raise S3OperationError(f"Unexpected S3 error: {e}")

def get_s3_object(s3, bucket, key):
    """
    Fetch object from S3 and return its bytes.
    Raises S3KeyNotFoundError if not found, S3OperationError for other errors.
    """
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        return resp['Body'].read()
    except s3.exceptions.NoSuchKey:
        raise S3KeyNotFoundError(f"S3 key not found: {key}")
    except s3.exceptions.ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchKey' or error_code == '404':
            raise S3KeyNotFoundError(f"S3 key not found: {key}")
        raise S3OperationError(f"S3 error fetching key '{key}': {e}")
    except Exception as e:
        raise S3OperationError(f"Unexpected S3 error: {e}")

def put_s3_object(s3, bucket, key, data, ext):
    """
    Put object to S3 with correct content type and public-read ACL.
    Raises S3OperationError for S3 errors.
    """
    content_type = ext_to_content_type(ext)
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type, ACL='public-read')
    except Exception as e:
        raise S3OperationError(f"Failed to store object '{key}' in S3: {e}")

def resize_image(img_bytes, width, height, ext):
    """
    Resize image bytes to (width, height) and return bytes.
    Raises ImageProcessingError for image processing errors.
    """
    try:
        with Image.open(io.BytesIO(img_bytes)) as img:
            img = img.convert('RGB') if ext in ['.jpg', '.jpeg'] else img.convert('RGBA')
            img = img.resize((width, height), Image.LANCZOS)
            out = io.BytesIO()
            save_format = 'JPEG' if ext in ['.jpg', '.jpeg'] else ext[1:].upper()
            img.save(out, format=save_format)
            return out.getvalue()
    except Exception as e:
        raise ImageProcessingError(f"Failed to resize/process image: {e}")

def ext_to_content_type(ext):
    """
    Map file extension to content type.
    """
    return {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.webp': 'image/webp',
    }.get(ext, 'application/octet-stream')

def s3_image_response(s3, bucket, key, ext):
    """
    Return image from S3 as Lambda response.
    """
    img_bytes = get_s3_object(s3, bucket, key)
    return image_response(img_bytes, ext)

def image_response(img_bytes, ext):
    """
    Return image bytes as Lambda proxy response.
    """
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': ext_to_content_type(ext),
            'Cache-Control': 'max-age=31536000, public',
        },
        'body': base64.b64encode(img_bytes).decode('utf-8'),
        'isBase64Encoded': True,
    }

def error_response(status, message, error_type=None):
    """
    Return error as Lambda proxy response, including errorType for debugging.
    """
    body = {"error": message}
    if error_type:
        body["errorType"] = error_type
    import json
    return {
        'statusCode': status,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(body),
    } 