# Lambda Image Resizer

---

## How the Flow Works (CloudFront + Lambda Explainer)

This solution enables on-demand image resizing and efficient CDN caching using AWS CloudFront, S3, and Lambda. Here's how the flow works:

1. **Client requests a resized image**
   - Example: `GET https://cdn.domain.com/assets/23/2345454_s_400_70.jpg`

2. **CloudFront checks its cache**
   - If the image is cached, it is returned immediately.
   - If not cached, CloudFront forwards the request to the S3 origin.

3. **S3 origin lookup**
   - If `assets/23/2345454_s_400_70.jpg` exists in S3, it is returned to CloudFront and cached for future requests.
   - If it does **not** exist, S3 returns a 403/404 error.

4. **CloudFront custom error response**
   - CloudFront is configured to redirect 403/404 errors to an API Gateway endpoint (e.g., `/image/assets/23/2345454_s_400_70.jpg`), which triggers the Lambda resizer.

5. **Lambda resizer logic**
   - Lambda parses the request path and extracts:
     - Directory: `assets/23/`
     - Filename: `2345454_s_400_70.jpg`
     - Original image: `2345454_original.jpg`
     - Width: `400`, Height: `70`
   - Lambda checks if the original image exists in S3.
     - If not, returns a 404 error.
   - If found, Lambda resizes the image using Pillow, saves the new file as `2345454_s_400_70.jpg` in S3, and returns a **301 redirect** to the CloudFront URL for the resized image.

6. **Client follows the redirect**
   - The client/browser automatically follows the redirect to the CloudFront URL, which now serves the newly generated and cached image.

**Result:**
- The first request for a new size triggers Lambda to generate and store the image.
- All subsequent requests are served instantly from CloudFront's cache.
- If the original image changes, you can invalidate the cached resized images in CloudFront.

---

## CloudFront Setup & Caching Policies

### 1. **CloudFront Origin and Behaviors**
- **Origin:** S3 bucket containing your images.
- **Behavior:**
  - Path pattern: `assets/*` (or as needed)
  - Origin: S3 bucket
  - Viewer protocol policy: Redirect HTTP to HTTPS (recommended)
  - Allowed HTTP methods: GET, HEAD
  - **Cache policy:**
    - Cache based on all query strings (if any)
    - Cache based on all headers (if needed)
    - Set TTLs as appropriate for your use case (e.g., min/max/default TTL)

### 2. **Custom Error Response to API Gateway**
- Configure CloudFront to handle 403/404 errors from S3:
  - **Error code:** 403, 404
  - **Response:** Redirect to your API Gateway endpoint (e.g., `/image/assets/23/2345454_s_400_70.jpg`)
  - **HTTP response code:** 200 (or as required by your API Gateway setup)

### 3. **Cache Invalidation When Original Image Changes**
- If you upload a new version of an original image (e.g., `2345454_original.jpg`), you must invalidate all cached resized versions in CloudFront.
- **Recommended approach:**
  - Use the AWS CLI or Console to create an invalidation for the relevant resized image paths, e.g.:
    ```bash
    aws cloudfront create-invalidation --distribution-id <DISTRIBUTION_ID> --paths "/assets/23/2345454_s_*.jpg"
    ```
  - This will invalidate all resized versions for that image.
- **Best practice:**
  - Automate invalidation as part of your image upload/deployment pipeline if originals are updated frequently.
  - Optionally, use versioning in the original filename (e.g., `2345454_v2_original.jpg`) to avoid cache issues and keep old versions available.

### 4. **General Caching Tips**
- Set long TTLs for resized images in CloudFront for best performance.
- Invalidate only when the original changes to minimize cache churn and cost.
- Ensure your Lambda returns appropriate cache headers (already set to `max-age=31536000, public`).

---

## Filename Conventions

- **Original images:** `<name>_original.<ext>` (e.g., `2345454_original.jpg`)
- **Resized images:** `<name>_s_<width>_<height>.<ext>` (e.g., `2345454_s_400_70.jpg`)
- The Lambda will always look for the original image with the `_original` suffix and generate resized images using the `_s_` separator.

---

## Features
- Resizes images on-the-fly based on filename pattern (no query params needed)
- Caches resized images in S3 for future requests
- Supports `.jpg`, `.jpeg`, `.png`, `.webp`
- Designed for Lambda@Edge or API Gateway triggers
- Secure input validation and error handling
- All environment variables are configurable (see Configuration section)

---

## Requirements
- Python 3.8+
- AWS account with S3 and Lambda permissions
- [boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html), [Pillow](https://python-pillow.org/), [pytest](https://docs.pytest.org/), [moto](https://github.com/spulec/moto) (for tests)

---

## Configuration

All environment variables are configurable to suit your deployment:

| Variable         | Description                                      | Example Value                |
|------------------|--------------------------------------------------|------------------------------|
| `IMAGE_BUCKET`   | S3 bucket name for original and resized images   | `my-cdn-bucket`              |
| `S3_PREFIX`      | (Optional) S3 key prefix for all images          | `assets/`                    |
| `MAX_DIMENSION`  | (Optional) Maximum allowed width/height (int)    | `2000`                       |
| `EXECUTION_MODE` | (Optional) Set to `local` for local testing, or `live` for production | `local` or `live` |
| `CLOUDFRONT_URL` | (Optional) The base URL for CloudFront redirects | `https://cdn.domain.com`     |

Set these in your Lambda environment variables or your deployment pipeline.

---

## Setup (Local Development)

1. **Clone the repository**
   ```bash
   git clone https://github.com/baracoda/lambda-image-resizer.git
   cd lambda_image_resizer
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   pip install moto  # For running tests
   ```

3. **Set environment variables for S3 bucket and options**
   ```bash
   export IMAGE_BUCKET=your-s3-bucket-name
   export S3_PREFIX=assets/
   export MAX_DIMENSION=2000
   export EXECUTION_MODE=local  # Use 'local' for local testing, 'live' for production
   export CLOUDFRONT_URL=https://cdn.domain.com
   ```

---

## Running Tests

```bash
pytest tests/
```

---

## Local Testing Instructions

To test the Lambda image resizer locally:

1. **Set environment variables for local mode:**
   ```bash
   export IMAGE_BUCKET=your-s3-bucket-name
   export EXECUTION_MODE=local
   export CLOUDFRONT_URL=https://cdn.domain.com
   ```
   - You can also set `S3_PREFIX` and `MAX_DIMENSION` as needed.

2. **Run the test suite:**
   ```bash
   pytest tests/
   ```

3. **What to expect:**
   - All tests should pass.
   - The code will log that it is running in LOCAL execution mode.
   - AWS services (like S3) are mocked using the `moto` library, so no real AWS resources are used or billed.

4. **Custom local runs:**
   - You can invoke `lambda_handler` directly from a Python shell or script with mock events for further local testing.

---

## Deployment to AWS Lambda & Lambda@Edge

### 1. Package the Lambda
- Ensure all dependencies are included (use a Lambda Layer or package with your deployment zip):
  ```bash
  pip install --target ./package -r requirements.txt
  cp handler.py ./package/
  cd package && zip -r ../lambda_image_resizer.zip .
  ```
- The handler entry point is `handler.lambda_handler`.

### 2. Set Environment Variables
- `IMAGE_BUCKET` (required): S3 bucket for original and resized images
- `S3_PREFIX` (optional): S3 key prefix for all images (e.g., `assets/`)
- `MAX_DIMENSION` (optional): Maximum allowed width/height
- `EXECUTION_MODE` (optional): Set to `live` for production (default), or `local` for local testing/mocking
- `CLOUDFRONT_URL` (optional): The base URL for CloudFront redirects

### 3. IAM Permissions
- Grant the Lambda function the following S3 permissions:
  - `s3:GetObject`, `s3:PutObject`, `s3:HeadObject`

### 4. Deploy Lambda@Edge (CloudFront)
- **Create the Lambda function** in the N. Virginia (us-east-1) region (required for Lambda@Edge).
- **Attach the Lambda to your CloudFront distribution**:
  1. In the AWS Console, go to CloudFront > Your Distribution > Behaviors.
  2. Edit or create a behavior for your image path (e.g., `/assets/*`).
  3. Under "Lambda Function Associations", add your Lambda function to the "Origin Request" or "Viewer Request" event (Origin Request is recommended for S3-backed origins).
  4. Deploy the changes.
- **Note:** Lambda@Edge will replicate your function to AWS edge locations automatically.

### 5. (Alternative) Deploy via API Gateway
- Create an API Gateway endpoint that triggers your Lambda function.
- Configure your CDN or frontend to call the API Gateway endpoint for image requests.

---

## Example Usage

Request:
```
GET https://cdn.domain.com/assets/23/2345454_s_400_70.jpg
```
- If `/assets/23/2345454_s_400_70.jpg` exists in S3, it is returned.
- If not, the Lambda resizes `/assets/23/2345454_original.jpg` to 400x70, stores it as `/assets/23/2345454_s_400_70.jpg`, and returns a 301 redirect to the CloudFront URL.

---

## Example Error Responses

Here are some example error responses you may receive from the Lambda function:

### 1. Missing Original Image
```
{
  "error": "Original image not found. Please upload the original image.",
  "errorType": "NotFound"
}
```

### 2. Unsupported File Type
```
{
  "error": "Unsupported file type. Allowed: .jpg, .jpeg, .png, .webp",
  "errorType": "ValidationError"
}
```

### 3. Invalid Dimensions
```
{
  "error": "Width and height must be between 1 and 2000.",
  "errorType": "ValidationError"
}
```

### 4. Internal Error (e.g., S3 or image processing failure)
```
{
  "error": "Internal error: <details>",
  "errorType": "InternalError"
}
```

All error responses are returned with `Content-Type: application/json` and an appropriate HTTP status code (e.g., 400, 404, 500).

---

## Security Notes
- Only allows resizing of images with extensions: `.jpg`, `.jpeg`, `.png`, `.webp`
- Width and height are validated (default 1-2000, configurable)
- Uses least-privilege S3 access
- Handles errors gracefully and logs securely

---

## Deployment Best Practices: Excluding Test Dependencies

**Important:**
- Do **not** include test or mock dependencies (such as `moto`, `pytest`, etc.) in your production Lambda deployment package.
- These libraries are only needed for local development and testing.

### How to Exclude Test Dependencies

1. **Separate your dependencies:**
   - Keep only production dependencies (e.g., `boto3`, `Pillow`) in `requirements.txt`.
   - Create a `requirements-dev.txt` for development and testing:
     ```
     # requirements-dev.txt
     -r requirements.txt
     pytest
     moto
     ```

2. **Install only production dependencies for deployment:**
   ```bash
   pip install --target ./package -r requirements.txt
   cp handler.py ./package/
   cd package && zip -r ../lambda_image_resizer.zip .
   ```

3. **For local development and testing:**
   ```bash
   pip install -r requirements-dev.txt
   ```

4. **Verify your deployment package:**
   - Ensure `moto`, `pytest`, and other test-only libraries are **not** present in your deployment zip or Lambda Layer. 

---

## License
MIT 