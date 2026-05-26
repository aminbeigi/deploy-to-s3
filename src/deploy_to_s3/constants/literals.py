"""Deploy-related string and collection constants.

Holds boto3 client names, default paths, required environment variable names,
and the redacted placeholder used in CI-safe log output.
"""

S3_CLIENT_TYPE = "s3"
CLOUDFRONT_CLIENT_TYPE = "cloudfront"
DEFAULT_DIST_DIR_NAME = "dist"
INDEX_HTML_NAME = "index.html"
REQUIRED_ENV_VAR_NAMES = (
    "CLOUDFRONT_DISTRIBUTION_ID",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "AWS_S3_BUCKET_NAME",
)
REDACTED = "REDACTED"
