"""Deploy dist/ files to an AWS S3 bucket.

This module uploads build artifacts from a local ``dist/`` directory to an S3
bucket and optionally invalidates a CloudFront distribution cache.
"""

import logging
import mimetypes
import os
import sys
import time
from pathlib import Path

import boto3

_CLIENT_TYPE = "s3"
_DIST_DIR_NAME = "dist"


def _setup_logger() -> logging.Logger:
    """Configure and return the application logger.

    Logging is configured once via :func:`logging.basicConfig` to emit INFO-level
    records to stdout with a timestamp, level, source location, and message.

    Returns:
        The root logger instance used for deploy operations.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)-s - %(filename)s:%(lineno)d - %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger()


def _get_dist_dir(_base: Path | None = None) -> Path:
    """Resolve the local distribution directory path.

    Uses the ``DIST_PATH`` environment variable when set; otherwise resolves
    ``<base>/dist`` where ``base`` defaults to the project root (parent of this
    package).

    Args:
        _base: Optional project root used when ``DIST_PATH`` is unset. Defaults
            to the parent directory of this package.

    Returns:
        A :class:`~pathlib.Path` to the distribution directory.

    Raises:
        FileNotFoundError: If the resolved distribution directory does not exist.
    """
    if env_path := os.environ.get("DIST_PATH"):
        dist_dir = Path(env_path)
    else:
        base = _base or Path(__file__).resolve().parent.parent
        dist_dir = base / _DIST_DIR_NAME
    if not dist_dir.exists():
        raise FileNotFoundError(f"Dist directory not found: {dist_dir}")
    return dist_dir


def _upload_to_s3(
    s3,
    bucket_name: str,
    dist_dir: Path,
    logger: logging.Logger,
) -> None:
    """Upload all files under ``dist_dir`` to the given S3 bucket.

    Each file is stored with an object key equal to its path relative to
    ``dist_dir``. A ``ContentType`` is set when :mod:`mimetypes` can guess one.

    Args:
        s3: A boto3 S3 client (or compatible mock) with an ``upload_file`` method.
        bucket_name: Target S3 bucket name.
        dist_dir: Local directory whose files are uploaded recursively.
        logger: Logger used for progress and completion messages.
    """
    files = [path for path in dist_dir.rglob("*") if not path.is_dir()]
    logger.info(f"Starting S3 upload: file_count={len(files)}...")
    upload_start = time.time()
    for file_path in files:
        s3_key = file_path.relative_to(dist_dir).as_posix()
        content_type, _ = mimetypes.guess_type(str(file_path))
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        s3.upload_file(str(file_path), bucket_name, s3_key, ExtraArgs=extra_args)
    upload_elapsed_s = time.time() - upload_start
    logger.info(
        f"Successfully uploaded {len(files)} files to S3 in {upload_elapsed_s:.2f}s"
    )


def _invalidate_cloudfront(cloudfront, logger: logging.Logger) -> None:
    """Invalidate all paths on the configured CloudFront distribution.

    Reads ``CLOUDFRONT_DISTRIBUTION_ID`` from the environment and requests a
    wildcard invalidation for ``/*``.

    Args:
        cloudfront: A boto3 CloudFront client (or compatible mock) with a
            ``create_invalidation`` method.
        logger: Logger used for progress and completion messages.

    Raises:
        KeyError: If ``CLOUDFRONT_DISTRIBUTION_ID`` is not set in the environment.
    """
    logger.info("Starting CloudFront cache invalidation...")
    response = cloudfront.create_invalidation(
        DistributionId=os.environ["CLOUDFRONT_DISTRIBUTION_ID"],
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": ["/*"]},
            "CallerReference": str(int(time.time())),
        },
    )
    _ = response["Invalidation"]["Id"]
    logger.info("Successfully completed CloudFront cache invalidation")


def main() -> int:
    """Run the deploy workflow: upload to S3 and invalidate CloudFront.

    Expects the following environment variables:

    * ``AWS_ACCESS_KEY_ID``
    * ``AWS_SECRET_ACCESS_KEY``
    * ``AWS_REGION``
    * ``AWS_S3_BUCKET_NAME``
    * ``CLOUDFRONT_DISTRIBUTION_ID``

    Optional:

    * ``DIST_PATH`` — override the local distribution directory.

    Returns:
        ``0`` on success, ``1`` if any step fails.
    """
    logger = _setup_logger()
    try:
        logger.info("Starting application deploy to S3")
        aws_access_key_id = os.environ["AWS_ACCESS_KEY_ID"]
        aws_secret_access_key = os.environ["AWS_SECRET_ACCESS_KEY"]
        credentials = dict[str, str](
            region_name=os.environ["AWS_REGION"],
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )

        dist_dir = _get_dist_dir()
        _upload_to_s3(
            boto3.client(_CLIENT_TYPE, **credentials),
            os.environ["AWS_S3_BUCKET_NAME"],
            dist_dir,
            logger,
        )
        _invalidate_cloudfront(boto3.client("cloudfront", **credentials), logger)
        return 0
    except Exception as e:
        # Avoid logging exception strings to reduce chances
        # of leaking sensitive values in public CI logs.
        logger.error(f"Deploy failed with exception type: {type(e).__name__}")
        return 1
