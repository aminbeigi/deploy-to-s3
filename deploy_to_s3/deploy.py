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
from dataclasses import dataclass
from typing import TYPE_CHECKING

import boto3

if TYPE_CHECKING:
    from botocore.client import BaseClient
    from mypy_boto3_s3 import S3Client

_CLIENT_TYPE = "s3"
_CLOUDFRONT_CLIENT_TYPE = "cloudfront"
_DIST_DIR_NAME = "dist"
_REQUIRED_ENV = (
    "CLOUDFRONT_DISTRIBUTION_ID",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "AWS_S3_BUCKET_NAME",
)


@dataclass(frozen=True)
class EnvironmentConfig:
    """Immutable container for deploy environment configuration.

    Attributes:
        aws_access_key_id: AWS access key ID for authentication.
        aws_region: AWS region where the S3 bucket is hosted.
        aws_s3_bucket_name: Name of the target S3 bucket.
        aws_secret_access_key: AWS secret access key for authentication.
        cloudfront_distribution_id: CloudFront distribution ID to invalidate after deploy.
        dist_path: Resolved path to the local distribution directory to upload.
    """

    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str
    aws_s3_bucket_name: str
    cloudfront_distribution_id: str
    dist_path: Path


def _fetch_env_variables() -> EnvironmentConfig:
    """Fetch and validate required environment variables and resolve the dist directory.

    Returns:
        An :class:`EnvironmentConfig` with ``cloudfront_distribution_id``,
        ``aws_access_key_id``, ``aws_secret_access_key``, ``aws_region``,
        ``aws_s3_bucket_name``, and ``dist_path`` (a resolved
        :class:`~pathlib.Path` to the distribution directory).

    Raises:
        EnvironmentError: If any required environment variable is missing or empty.
        FileNotFoundError: If the resolved distribution directory does not exist.
    """
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise EnvironmentError(
            f"The following environment variables are not set: {missing}"
        )

    env_path = os.environ.get("DIST_PATH")
    if env_path:
        dist_dir = Path(env_path)
    else:
        dist_dir = Path(__file__).resolve().parent.parent / _DIST_DIR_NAME
    if not dist_dir.exists():
        raise FileNotFoundError(f"Dist directory not found: {dist_dir}")

    return EnvironmentConfig(
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        aws_region=os.environ["AWS_REGION"],
        aws_s3_bucket_name=os.environ["AWS_S3_BUCKET_NAME"],
        cloudfront_distribution_id=os.environ["CLOUDFRONT_DISTRIBUTION_ID"],
        dist_path=dist_dir,
    )


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


def _upload_to_s3(
    s3: "S3Client",
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


def _invalidate_cloudfront(
    cloudfront: "BaseClient", distribution_id: str, logger: logging.Logger
) -> None:
    """Invalidate all paths on the configured CloudFront distribution.

    Args:
        cloudfront: A boto3 CloudFront client (or compatible mock) with a
            ``create_invalidation`` method.
        distribution_id: The CloudFront distribution ID to invalidate.
        logger: Logger used for progress and completion messages.
    """
    logger.info("Starting CloudFront cache invalidation...")
    response = cloudfront.create_invalidation(
        DistributionId=distribution_id,
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
    environment_variables = _fetch_env_variables()
    try:
        logger.info("Starting application deploy to S3")
        _upload_to_s3(
            boto3.client(
                _CLIENT_TYPE,
                region_name=environment_variables.aws_region,
                aws_access_key_id=environment_variables.aws_access_key_id,
                aws_secret_access_key=environment_variables.aws_secret_access_key,
            ),
            environment_variables.aws_s3_bucket_name,
            environment_variables.dist_path,
            logger,
        )
        _invalidate_cloudfront(
            boto3.client(
                _CLOUDFRONT_CLIENT_TYPE,
                region_name=environment_variables.aws_region,
                aws_access_key_id=environment_variables.aws_access_key_id,
                aws_secret_access_key=environment_variables.aws_secret_access_key,
            ),
            environment_variables.cloudfront_distribution_id,
            logger,
        )
        return 0
    except Exception as e:
        # Avoid logging exception strings to reduce chances
        # of leaking sensitive values in public CI logs.
        logger.error(f"Deploy failed with exception type: {type(e).__name__}")
        return 1
