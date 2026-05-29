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
from typing import TYPE_CHECKING

import boto3

from deploy_to_s3.cli import parse_args
from deploy_to_s3.constants.literals import (
    CLOUDFRONT_CLIENT_TYPE,
    DEFAULT_DIST_DIR_NAME,
    INDEX_HTML_NAME,
    REDACTED,
    REQUIRED_ENV_VAR_NAMES,
    S3_CLIENT_TYPE,
)
from deploy_to_s3.constants.models import DeploySummary, EnvironmentConfig, UploadStats
from deploy_to_s3.logger import configure_logging, get_logger

if TYPE_CHECKING:
    from botocore.client import BaseClient
    from mypy_boto3_s3 import S3Client

logger = get_logger(__name__)


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
    logger.info("Starting environment variable fetch...")
    missing = [name for name in REQUIRED_ENV_VAR_NAMES if not os.environ.get(name)]
    if missing:
        raise EnvironmentError(
            f"The following environment variables are not set: {missing}"
        )

    env_path = os.environ.get("DIST_PATH")
    if env_path:
        dist_dir = Path(env_path)
    else:
        dist_dir = Path(__file__).resolve().parent.parent / DEFAULT_DIST_DIR_NAME
    if not dist_dir.exists():
        raise FileNotFoundError(f"Dist directory not found: {dist_dir}")

    logger.info("Successfully fetched environment variables")
    return EnvironmentConfig(
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        aws_region=os.environ["AWS_REGION"],
        aws_s3_bucket_name=os.environ["AWS_S3_BUCKET_NAME"],
        cloudfront_distribution_id=os.environ["CLOUDFRONT_DISTRIBUTION_ID"],
        dist_path=dist_dir,
    )


def _log_deploy_summary(summary: DeploySummary) -> None:
    """Log a multi-line deploy summary to stdout and the log file.

    Infrastructure identifiers (bucket, distribution, invalidation) are always
    logged as :data:`REDACTED` so GitHub Actions job output never exposes
    values passed in via repository secrets.

    Args:
        summary: Aggregated deploy metrics from upload and invalidation.
    """
    logger.info("Deploy summary:")
    logger.info(f"  Files uploaded: {summary.file_count}")
    logger.info(f"  Bytes uploaded: {summary.bytes_uploaded}")
    logger.info(f"  Upload duration: {summary.upload_duration_seconds:.2f}s")
    logger.info(f"  S3 bucket: {REDACTED}")
    logger.info(f"  CloudFront distribution: {REDACTED}")
    logger.info(f"  CloudFront invalidation: {REDACTED}")


def _list_dist_files(dist_dir: Path) -> list[Path]:
    """Return every file path under ``dist_dir``, recursively.

    Args:
        dist_dir: Local distribution directory to scan.

    Returns:
        Paths to regular files only (directories are excluded).
    """
    return [path for path in dist_dir.rglob("*") if not path.is_dir()]


def _validate_dist_directory(dist_dir: Path) -> None:
    """Validate that the distribution directory is ready to deploy.

    Catches empty builds and missing entry HTML before any S3 upload runs.

    Args:
        dist_dir: Local directory whose contents will be uploaded.

    Raises:
        ValueError: If the directory contains no files or is missing
            ``index.html`` at the directory root.
    """
    logger.info("Starting dist directory validation...")
    files = _list_dist_files(dist_dir)
    if not files:
        raise ValueError("Dist directory contains no files")
    index_html = dist_dir / INDEX_HTML_NAME
    if not index_html.is_file():
        raise ValueError("Dist directory is missing index.html at the root")
    logger.info("Successfully validated dist directory")


def _upload_to_s3(
    s3: "S3Client",
    bucket_name: str,
    dist_dir: Path,
) -> UploadStats:
    """Upload all files under ``dist_dir`` to the given S3 bucket.

    Each file is stored with an object key equal to its path relative to
    ``dist_dir``. A ``ContentType`` is set when :mod:`mimetypes` can guess one.

    Args:
        s3: A boto3 S3 client (or compatible mock) with an ``upload_file`` method.
        bucket_name: Target S3 bucket name.
        dist_dir: Local directory whose files are uploaded recursively.

    Returns:
        Upload metrics including file count, total bytes, and duration.
    """
    files = _list_dist_files(dist_dir)
    bytes_uploaded = sum(file_path.stat().st_size for file_path in files)
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
    return UploadStats(
        file_count=len(files),
        bytes_uploaded=bytes_uploaded,
        upload_duration_seconds=upload_elapsed_s,
    )


def _invalidate_cloudfront(
    cloudfront: "BaseClient",
    distribution_id: str,
) -> str:
    """Invalidate all paths on the configured CloudFront distribution.

    Args:
        cloudfront: A boto3 CloudFront client (or compatible mock) with a
            ``create_invalidation`` method.
        distribution_id: The CloudFront distribution ID to invalidate.

    Returns:
        The CloudFront invalidation ID from the API response.

    Raises:
        RuntimeError: If the CloudFront API returns a non-201 status code.
    """
    logger.info("Starting CloudFront cache invalidation...")
    response = cloudfront.create_invalidation(
        DistributionId=distribution_id,
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": ["/*"]},
            "CallerReference": str(int(time.time())),
        },
    )
    status_code = response["ResponseMetadata"]["HTTPStatusCode"]
    invalidation_id = response.get("Invalidation", {}).get("Id", "unknown")
    if status_code != 201:
        raise RuntimeError(
            f"CloudFront invalidation failed with status {status_code}: id={invalidation_id}"
        )
    logger.info("Successfully completed CloudFront cache invalidation")
    return invalidation_id


def run(dry_run: bool = False) -> None:
    """Orchestrate the deploy workflow: upload to S3 and invalidate CloudFront.

    When ``dry_run`` is ``True``, all validation steps run as normal but no AWS
    calls are made. The files that would be uploaded are logged instead.

    Expects the following environment variables:

    * ``AWS_ACCESS_KEY_ID``
    * ``AWS_SECRET_ACCESS_KEY``
    * ``AWS_REGION``
    * ``AWS_S3_BUCKET_NAME``
    * ``CLOUDFRONT_DISTRIBUTION_ID``

    Optional:

    * ``DIST_PATH`` — override the local distribution directory.

    Args:
        dry_run: When ``True``, skip all AWS side effects and log planned actions only.
    """
    logger.info("Starting deploy-to-s3...")
    environment_variables = _fetch_env_variables()
    _validate_dist_directory(environment_variables.dist_path)
    if dry_run:
        logger.info("Dry run: skipping S3 upload and CloudFront invalidation")
        upload_stats = UploadStats(
            file_count=0,
            bytes_uploaded=0,
            upload_duration_seconds=0.0,
        )
    else:
        upload_stats = _upload_to_s3(
            boto3.client(
                S3_CLIENT_TYPE,
                region_name=environment_variables.aws_region,
                aws_access_key_id=environment_variables.aws_access_key_id,
                aws_secret_access_key=environment_variables.aws_secret_access_key,
            ),
            environment_variables.aws_s3_bucket_name,
            environment_variables.dist_path,
        )
        _invalidate_cloudfront(
            boto3.client(
                CLOUDFRONT_CLIENT_TYPE,
                region_name=environment_variables.aws_region,
                aws_access_key_id=environment_variables.aws_access_key_id,
                aws_secret_access_key=environment_variables.aws_secret_access_key,
            ),
            environment_variables.cloudfront_distribution_id,
        )
        logger.info("Successfully deployed to S3")
    _log_deploy_summary(
        DeploySummary(
            file_count=upload_stats.file_count,
            bytes_uploaded=upload_stats.bytes_uploaded,
            upload_duration_seconds=upload_stats.upload_duration_seconds,
        )
    )


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, configure logging, and run the deploy pipeline.

    Args:
        argv: Argument list to parse. Defaults to ``sys.argv[1:]`` when ``None``.

    Returns:
        ``0`` on success, ``1`` on any unhandled exception.
    """
    args = parse_args(argv)
    configure_logging(level=logging.INFO)
    try:
        run(dry_run=args.dry_run)
        return 0
    except Exception as exc:
        logger.error(
            f"Fatal error ({type(exc).__name__})",
            exc_info=logger.isEnabledFor(logging.DEBUG),
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
