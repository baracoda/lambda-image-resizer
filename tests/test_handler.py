import os
import io
import base64
import pytest
from unittest.mock import patch
from moto import mock_aws
import boto3
from PIL import Image

# Import the handler
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from handler import lambda_handler

BUCKET = 'test-bucket'

@pytest.fixture(autouse=True)
def skip_if_live_mode():
    if os.environ.get('EXECUTION_MODE', 'local').lower() == 'live':
        pytest.skip('Skipping tests in live execution mode.')

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setenv('IMAGE_BUCKET', BUCKET)

@mock_aws
def test_valid_resize_and_return():
    # Set up S3 and upload a test image
    s3 = boto3.client('s3')
    s3.create_bucket(Bucket=BUCKET)
    img = Image.new('RGB', (200, 200), color='red')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    s3.put_object(Bucket=BUCKET, Key='assets/image_original.jpg', Body=buf.getvalue())

    event = {
        'path': '/assets/image.jpg',
        'queryStringParameters': {'w': '100', 'h': '50'}
    }
    resp = lambda_handler(event, None)
    assert resp['statusCode'] == 200
    assert resp['isBase64Encoded']
    img_bytes = base64.b64decode(resp['body'])
    out_img = Image.open(io.BytesIO(img_bytes))
    assert out_img.size == (100, 50)

@mock_aws
def test_missing_original_image():
    s3 = boto3.client('s3')
    s3.create_bucket(Bucket=BUCKET)
    event = {
        'path': '/assets/missing.jpg',
        'queryStringParameters': {'w': '100', 'h': '50'}
    }
    resp = lambda_handler(event, None)
    assert resp['statusCode'] == 404
    assert 'Original image not found' in resp['body']

@mock_aws
def test_invalid_parameters():
    s3 = boto3.client('s3')
    s3.create_bucket(Bucket=BUCKET)
    event = {
        'path': '/assets/image.jpg',
        'queryStringParameters': {'w': '0', 'h': '9999'}
    }
    resp = lambda_handler(event, None)
    assert resp['statusCode'] == 400

@mock_aws
def test_unsupported_file_type():
    s3 = boto3.client('s3')
    s3.create_bucket(Bucket=BUCKET)
    event = {
        'path': '/assets/image.bmp',
        'queryStringParameters': {'w': '100', 'h': '50'}
    }
    resp = lambda_handler(event, None)
    assert resp['statusCode'] == 400
    assert 'Unsupported file type' in resp['body'] 