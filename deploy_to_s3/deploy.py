"""Deploy dist/ files to an AWS S3 bucket."""

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
    """Configure basic logging to stdout."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)-s - %(filename)s:%(lineno)d - %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger()


def _get_dist_dir(_base: Path | None = None) -> Path:
    if env_path := os.environ.get("DIST_PATH"):
        dist_dir = Path(env_path)
    else:
        base = _base or Path(__file__).resolve().parent.parent
        dist_dir = base / _DIST_DIR_NAME
    if not dist_dir.exists():
        raise FileNotFoundError(f"dist directory not found: {dist_dir}")
    return dist_dir


def _upload_to_s3(s3, bucket_name: str, dist_dir: Path, logger: logging.Logger) -> None:
    files = [path for path in dist_dir.rglob("*") if not path.is_dir()]
    logger.info(f"starting s3 upload: file_count={len(files)}...")
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
        f"successfully uploaded {len(files)} files to s3 in {upload_elapsed_s:.2f}s"
    )


def _invalidate_cloudfront(cloudfront, logger: logging.Logger) -> None:
    logger.info("starting cloudfront cache invalidation...")
    response = cloudfront.create_invalidation(
        DistributionId=os.environ["CLOUDFRONT_DISTRIBUTION_ID"],
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": ["/*"]},
            "CallerReference": str(int(time.time())),
        },
    )
    _ = response["Invalidation"]["Id"]
    logger.info("successfully completed cloudfront cache invalidation")


def main() -> int:
    logger = _setup_logger()
    try:
        logger.info("starting application deploy to s3")
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
        logger.error(f"deploy failed with exception type: {type(e).__name__}")
        return 1
