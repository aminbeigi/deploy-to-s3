"""Tests for deploy_to_s3.deploy.

Covers environment validation, S3 upload behaviour, CloudFront invalidation,
and the main() orchestration entry point.
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deploy_to_s3.constants.models import EnvironmentConfig, UploadStats
from deploy_to_s3.deploy import (
    _fetch_env_variables,
    _invalidate_cloudfront,
    _log_deploy_summary,
    _upload_to_s3,
    _validate_dist_directory,
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
    (dist / "index.html").write_text("<html></html>")
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


class TestValidateDistDirectory:
    """Validate dist/ guards before upload."""

    def test_raises_when_dist_has_no_files(self, dist_dir: Path) -> None:
        """Raise ValueError when the dist directory exists but has no files.

        Args:
            dist_dir: Temporary dist directory with only the default index.html removed.
        """
        (dist_dir / "index.html").unlink()
        with pytest.raises(ValueError, match="contains no files"):
            _validate_dist_directory(dist_dir)

    def test_raises_when_index_html_missing(self, dist_dir: Path) -> None:
        """Raise ValueError when files exist but root index.html is absent.

        Args:
            dist_dir: Temporary dist directory with assets but no index.html.
        """
        (dist_dir / "index.html").unlink()
        assets = dist_dir / "assets"
        assets.mkdir()
        (assets / "app.js").write_text("console.log(1)")
        with pytest.raises(ValueError, match="missing index.html"):
            _validate_dist_directory(dist_dir)

    def test_passes_when_index_html_at_root(self, dist_dir: Path) -> None:
        """Accept a dist tree that includes index.html at the root.

        Args:
            dist_dir: Temporary dist directory with the default index.html.
        """
        _validate_dist_directory(dist_dir)


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

        stats = _upload_to_s3(mock_s3, "my-bucket", dist_dir)

        assert mock_s3.upload_file.call_count == 2
        assert stats.file_count == 2
        assert stats.bytes_uploaded > 0
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

    def test_creates_wildcard_invalidation(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Issue a wildcard invalidation so all cached objects are purged.

        Args:
            caplog: pytest fixture for capturing log output.
        """
        mock_cf = MagicMock()
        mock_cf.create_invalidation.return_value = {
            "Invalidation": {"Id": "INV123"},
            "ResponseMetadata": {"HTTPStatusCode": 201},
        }

        with caplog.at_level(logging.INFO):
            invalidation_id = _invalidate_cloudfront(mock_cf, "E1234567890")

        assert invalidation_id == "INV123"
        kwargs = mock_cf.create_invalidation.call_args.kwargs
        assert kwargs["DistributionId"] == "E1234567890"
        assert kwargs["InvalidationBatch"]["Paths"]["Items"] == ["/*"]
        assert kwargs["InvalidationBatch"]["Paths"]["Quantity"] == 1
        assert "Successfully completed CloudFront cache invalidation" in caplog.text

    def test_raises_when_status_code_not_201(self) -> None:
        """Raise RuntimeError when the CloudFront API returns a non-201 status code.

        Args:
            None
        """
        mock_cf = MagicMock()
        mock_cf.create_invalidation.return_value = {
            "Invalidation": {"Id": "INV123"},
            "ResponseMetadata": {"HTTPStatusCode": 500},
        }

        with pytest.raises(
            RuntimeError,
            match=r"CloudFront invalidation failed with status 500: id=INV123",
        ):
            _invalidate_cloudfront(mock_cf, "E1234567890")


class TestLogDeploySummary:
    """Validate deploy summary logging."""

    def test_logs_file_count_and_bytes(self, caplog: pytest.LogCaptureFixture) -> None:
        """Log file count, bytes uploaded, and duration without secret values.

        Args:
            caplog: pytest fixture for capturing log output.
        """
        summary = UploadStats(
            file_count=3,
            bytes_uploaded=2048,
            upload_duration_seconds=1.25,
        )
        with caplog.at_level(logging.INFO):
            _log_deploy_summary(summary)

        assert "Deploy summary:" in caplog.text
        assert "Files uploaded: 3" in caplog.text
        assert "Bytes uploaded: 2048" in caplog.text
        assert "Upload duration: 1.25s" in caplog.text
        assert "S3 bucket: REDACTED" in caplog.text
        assert "CloudFront distribution: REDACTED" in caplog.text
        assert "CloudFront invalidation: REDACTED" in caplog.text


class TestMain:
    """Validate the main() entry point orchestration and error handling."""

    @patch("deploy_to_s3.deploy.boto3.client")
    def test_success_runs_full_deploy_pipeline(
        self,
        mock_boto_client: MagicMock,
        dist_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        aws_env: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Return 0 and invoke both S3 upload and CloudFront invalidation on success.

        Args:
            mock_boto_client: Patched boto3.client that returns mock S3 and CloudFront clients.
            dist_dir: Temporary dist directory containing a single file to upload.
            monkeypatch: pytest fixture for patching environment variables.
            aws_env: Fixture that sets all required AWS environment variables.
            caplog: pytest fixture for capturing log output.
        """
        (dist_dir / "index.html").write_text("hello")
        monkeypatch.setenv("DIST_PATH", str(dist_dir))
        mock_s3, mock_cf = MagicMock(), MagicMock()
        mock_cf.create_invalidation.return_value = {
            "Invalidation": {"Id": "INV1"},
            "ResponseMetadata": {"HTTPStatusCode": 201},
        }

        def _make_client(svc: str, **_: object) -> MagicMock:
            if svc == "s3":
                return mock_s3
            return mock_cf

        mock_boto_client.side_effect = _make_client

        with caplog.at_level(logging.INFO):
            assert main([]) == 0
        mock_s3.upload_file.assert_called_once()
        mock_cf.create_invalidation.assert_called_once()
        assert "Deploy summary:" in caplog.text
        assert "Files uploaded: 1" in caplog.text
        assert "S3 bucket: REDACTED" in caplog.text
        assert "CloudFront distribution: REDACTED" in caplog.text
        assert "CloudFront invalidation: REDACTED" in caplog.text
        assert "test-bucket" not in caplog.text
        assert "E1234567890" not in caplog.text
        assert "INV1" not in caplog.text
        mock_boto_client.assert_any_call(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test-key-id",
            aws_secret_access_key="test-secret",
        )

    @patch("deploy_to_s3.deploy.boto3.client")
    def test_dry_run_skips_aws_calls(
        self,
        mock_boto_client: MagicMock,
        dist_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        aws_env: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Return 0, make no AWS calls, and log planned upload details in dry-run mode.

        Args:
            mock_boto_client: Patched boto3.client, asserted to never be called.
            dist_dir: Temporary dist directory with an HTML file and a JS asset.
            monkeypatch: pytest fixture for patching environment variables.
            aws_env: Fixture that sets all required AWS environment variables.
            caplog: pytest fixture for capturing log output.
        """
        (dist_dir / "index.html").write_text("<html></html>")
        assets = dist_dir / "assets"
        assets.mkdir()
        (assets / "app.js").write_text("console.log(1)")
        monkeypatch.setenv("DIST_PATH", str(dist_dir))

        with caplog.at_level(logging.INFO):
            assert main(["--dry-run"]) == 0

        mock_boto_client.assert_not_called()
        assert "Would upload: index.html" in caplog.text
        assert "Would upload: assets/app.js" in caplog.text
        assert "skipping CloudFront invalidation" in caplog.text
        assert "Deploy summary:" in caplog.text
        assert "Files uploaded: 2" in caplog.text

    @patch("deploy_to_s3.deploy.boto3.client")
    def test_returns_1_when_dist_missing(
        self,
        mock_boto_client: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        aws_env: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Return 1 and log the error message when the dist directory does not exist.

        Args:
            mock_boto_client: Patched boto3.client, asserted to never be called.
            tmp_path: pytest-provided temporary directory used to construct a nonexistent path.
            monkeypatch: pytest fixture for patching environment variables.
            aws_env: Fixture that sets all required AWS environment variables.
            caplog: pytest fixture for capturing log output.
        """
        monkeypatch.setenv("DIST_PATH", str(tmp_path / "missing"))
        with caplog.at_level(logging.ERROR):
            assert main([]) == 1
        assert "Fatal error (FileNotFoundError)" in caplog.text
        mock_boto_client.assert_not_called()

    @patch("deploy_to_s3.deploy.boto3.client")
    def test_returns_1_when_dist_has_no_files(
        self,
        mock_boto_client: MagicMock,
        dist_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        aws_env: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Return 1 without calling AWS when dist contains no files.

        Args:
            mock_boto_client: Patched boto3.client, asserted to never be called.
            dist_dir: Temporary dist directory cleared of all files.
            monkeypatch: pytest fixture for patching environment variables.
            aws_env: Fixture that sets all required AWS environment variables.
            caplog: pytest fixture for capturing log output.
        """
        (dist_dir / "index.html").unlink()
        monkeypatch.setenv("DIST_PATH", str(dist_dir))
        with caplog.at_level(logging.ERROR):
            assert main([]) == 1
        assert "Fatal error (ValueError)" in caplog.text
        mock_boto_client.assert_not_called()

    @patch("deploy_to_s3.deploy.boto3.client")
    def test_returns_1_when_index_html_missing(
        self,
        mock_boto_client: MagicMock,
        dist_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        aws_env: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Return 1 without calling AWS when root index.html is missing.

        Args:
            mock_boto_client: Patched boto3.client, asserted to never be called.
            dist_dir: Temporary dist directory with assets but no index.html.
            monkeypatch: pytest fixture for patching environment variables.
            aws_env: Fixture that sets all required AWS environment variables.
            caplog: pytest fixture for capturing log output.
        """
        (dist_dir / "index.html").unlink()
        (dist_dir / "assets").mkdir()
        (dist_dir / "assets" / "app.js").write_text("console.log(1)")
        monkeypatch.setenv("DIST_PATH", str(dist_dir))
        with caplog.at_level(logging.ERROR):
            assert main([]) == 1
        assert "Fatal error (ValueError)" in caplog.text
        mock_boto_client.assert_not_called()

    @patch("deploy_to_s3.deploy.boto3.client")
    def test_returns_1_when_aws_credentials_missing(
        self,
        mock_boto_client: MagicMock,
        dist_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Return 1 and log the error message when AWS credentials are not configured.

        Args:
            mock_boto_client: Patched boto3.client, asserted to never be called.
            dist_dir: Existing dist directory so only the credential check is exercised.
            monkeypatch: pytest fixture for patching environment variables.
            caplog: pytest fixture for capturing log output.
        """
        monkeypatch.setenv("DIST_PATH", str(dist_dir))
        with caplog.at_level(logging.ERROR):
            assert main([]) == 1
        assert "Fatal error (OSError)" in caplog.text
        mock_boto_client.assert_not_called()
