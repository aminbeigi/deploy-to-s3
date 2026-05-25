"""Tests for deploy_to_s3.deploy.

Covers environment validation, S3 upload behaviour, CloudFront invalidation,
and the main() orchestration entry point.
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deploy_to_s3.deploy import (
    EnvironmentConfig,
    _fetch_env_variables,
    _invalidate_cloudfront,
    _upload_to_s3,
    main,
)


@pytest.fixture
def aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Populate all required AWS environment variables with dummy values.

    Args:
        monkeypatch: pytest fixture for patching environment variables.
    """
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("CLOUDFRONT_DISTRIBUTION_ID", "E1234567890")


@pytest.fixture
def dist_dir(tmp_path: Path) -> Path:
    """Return a temporary dist directory that exists on disk.

    Args:
        tmp_path: pytest-provided temporary directory unique to each test.

    Returns:
        Path to the created dist directory.
    """
    dist = tmp_path / "dist"
    dist.mkdir()
    return dist


class TestFetchEnvVariables:
    """Validate that _fetch_env_variables enforces required configuration."""

    def test_raises_when_aws_credentials_missing(
        self, dist_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raise EnvironmentError when AWS environment variables are absent.

        Args:
            dist_dir: Existing dist directory so only the credential check is exercised.
            monkeypatch: pytest fixture for patching environment variables.
        """
        monkeypatch.setenv("DIST_PATH", str(dist_dir))
        with pytest.raises(EnvironmentError, match="environment variables are not set"):
            _fetch_env_variables()

    def test_raises_when_dist_directory_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aws_env: None
    ) -> None:
        """Raise FileNotFoundError when the dist path does not exist on disk.

        Args:
            tmp_path: pytest-provided temporary directory used to construct a nonexistent path.
            monkeypatch: pytest fixture for patching environment variables.
            aws_env: Fixture that sets all required AWS environment variables.
        """
        monkeypatch.setenv("DIST_PATH", str(tmp_path / "nonexistent"))
        with pytest.raises(FileNotFoundError, match="Dist directory not found"):
            _fetch_env_variables()

    def test_returns_valid_config(
        self, dist_dir: Path, monkeypatch: pytest.MonkeyPatch, aws_env: None
    ) -> None:
        """Return a fully populated EnvironmentConfig when all inputs are valid.

        Args:
            dist_dir: Existing dist directory to use as DIST_PATH.
            monkeypatch: pytest fixture for patching environment variables.
            aws_env: Fixture that sets all required AWS environment variables.
        """
        monkeypatch.setenv("DIST_PATH", str(dist_dir))
        config = _fetch_env_variables()
        assert isinstance(config, EnvironmentConfig)
        assert config.dist_path == dist_dir
        assert config.aws_region == "us-east-1"


class TestUploadToS3:
    """Validate S3 upload behaviour: key derivation and content-type headers."""

    def test_uploads_all_files_with_relative_keys(self, dist_dir: Path) -> None:
        """Upload every file under dist_dir using its path relative to dist_dir as the S3 key.

        Args:
            dist_dir: Temporary dist directory pre-populated with a nested file tree.
        """
        (dist_dir / "index.html").write_text("<html></html>")
        (dist_dir / "assets").mkdir()
        (dist_dir / "assets" / "app.js").write_text("console.log(1)")
        mock_s3 = MagicMock()

        _upload_to_s3(mock_s3, "my-bucket", dist_dir)

        assert mock_s3.upload_file.call_count == 2
        keys = {call.args[2] for call in mock_s3.upload_file.call_args_list}
        assert keys == {"index.html", "assets/app.js"}

    def test_sets_content_type_header(self, dist_dir: Path) -> None:
        """Set the ContentType ExtraArg so browsers receive the correct MIME type.

        Args:
            dist_dir: Temporary dist directory containing a single HTML file.
        """
        (dist_dir / "index.html").write_text("<html></html>")
        mock_s3 = MagicMock()

        _upload_to_s3(mock_s3, "my-bucket", dist_dir)

        _, kwargs = mock_s3.upload_file.call_args
        assert kwargs["ExtraArgs"]["ContentType"] == "text/html"


class TestInvalidateCloudFront:
    """Validate that CloudFront cache invalidation targets all paths."""

    def test_creates_wildcard_invalidation(self) -> None:
        """Issue a wildcard invalidation so all cached objects are purged."""
        mock_cf = MagicMock()
        mock_cf.create_invalidation.return_value = {"Invalidation": {"Id": "INV123"}}

        _invalidate_cloudfront(mock_cf, "E1234567890")

        kwargs = mock_cf.create_invalidation.call_args.kwargs
        assert kwargs["DistributionId"] == "E1234567890"
        assert kwargs["InvalidationBatch"]["Paths"]["Items"] == ["/*"]
        assert kwargs["InvalidationBatch"]["Paths"]["Quantity"] == 1


class TestMain:
    """Validate the main() entry point orchestration and error handling."""

    @patch("deploy_to_s3.deploy.boto3.client")
    def test_success_runs_full_deploy_pipeline(
        self,
        mock_boto_client: MagicMock,
        dist_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        aws_env: None,
    ) -> None:
        """Return 0 and invoke both S3 upload and CloudFront invalidation on success.

        Args:
            mock_boto_client: Patched boto3.client that returns mock S3 and CloudFront clients.
            dist_dir: Temporary dist directory containing a single file to upload.
            monkeypatch: pytest fixture for patching environment variables.
            aws_env: Fixture that sets all required AWS environment variables.
        """
        (dist_dir / "index.html").write_text("hello")
        monkeypatch.setenv("DIST_PATH", str(dist_dir))
        mock_s3, mock_cf = MagicMock(), MagicMock()
        mock_cf.create_invalidation.return_value = {"Invalidation": {"Id": "INV1"}}
        mock_boto_client.side_effect = lambda svc, **_: mock_s3 if svc == "s3" else mock_cf

        assert main() == 0
        mock_s3.upload_file.assert_called_once()
        mock_cf.create_invalidation.assert_called_once()
        mock_boto_client.assert_any_call(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test-key-id",
            aws_secret_access_key="test-secret",
        )

    @patch("deploy_to_s3.deploy.boto3.client")
    def test_returns_1_when_dist_missing(
        self,
        mock_boto_client: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        aws_env: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Return 1 and log the error type when the dist directory does not exist.

        Args:
            mock_boto_client: Patched boto3.client, asserted to never be called.
            tmp_path: pytest-provided temporary directory used to construct a nonexistent path.
            monkeypatch: pytest fixture for patching environment variables.
            aws_env: Fixture that sets all required AWS environment variables.
            caplog: pytest fixture for capturing log output.
        """
        monkeypatch.setenv("DIST_PATH", str(tmp_path / "missing"))
        with caplog.at_level(logging.ERROR):
            assert main() == 1
        assert "Failed deploy: FileNotFoundError" in caplog.text
        mock_boto_client.assert_not_called()

    @patch("deploy_to_s3.deploy.boto3.client")
    def test_returns_1_when_aws_credentials_missing(
        self,
        mock_boto_client: MagicMock,
        dist_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Return 1 and log the error type when AWS credentials are not configured.

        Args:
            mock_boto_client: Patched boto3.client, asserted to never be called.
            dist_dir: Existing dist directory so only the credential check is exercised.
            monkeypatch: pytest fixture for patching environment variables.
            caplog: pytest fixture for capturing log output.
        """
        monkeypatch.setenv("DIST_PATH", str(dist_dir))
        with caplog.at_level(logging.ERROR):
            assert main() == 1
        assert "Failed deploy: OSError" in caplog.text
        mock_boto_client.assert_not_called()
