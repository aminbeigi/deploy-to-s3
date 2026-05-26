"""Immutable data containers for deploy configuration and metrics."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UploadStats:
    """Metrics collected while uploading files to S3.

    Attributes:
        bytes_uploaded: Total size in bytes of all uploaded files.
        file_count: Number of files uploaded.
        upload_duration_seconds: Wall-clock time spent uploading.
    """

    file_count: int
    bytes_uploaded: int
    upload_duration_seconds: float


@dataclass(frozen=True)
class DeploySummary:
    """End-of-deploy statistics for logging.

    Attributes:
        bytes_uploaded: Total size in bytes of all uploaded files.
        file_count: Number of files uploaded.
        upload_duration_seconds: Wall-clock time spent uploading to S3.
    """

    file_count: int
    bytes_uploaded: int
    upload_duration_seconds: float


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
