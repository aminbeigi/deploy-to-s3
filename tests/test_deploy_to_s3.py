import logging
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
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("CLOUDFRONT_DISTRIBUTION_ID", "E1234567890")


def test_fetch_env_variables_raises_when_dist_missing(tmp_path, aws_env):
    with pytest.raises(FileNotFoundError, match="Dist directory not found"):
        _fetch_env_variables()


def test_fetch_env_variables_uses_dist_path_env_var(tmp_path, monkeypatch, aws_env):
    dist = tmp_path / "out"
    dist.mkdir()
    monkeypatch.setenv("DIST_PATH", str(dist))
    config = _fetch_env_variables()
    assert config.dist_path == dist
    assert isinstance(config, EnvironmentConfig)


def test_fetch_env_variables_dist_path_raises_when_missing(
    tmp_path, monkeypatch, aws_env
):
    monkeypatch.setenv("DIST_PATH", str(tmp_path / "nonexistent"))
    with pytest.raises(FileNotFoundError, match="Dist directory not found"):
        _fetch_env_variables()


def test_fetch_env_variables_raises_when_required_env_missing(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    monkeypatch.setenv("DIST_PATH", str(dist))
    with pytest.raises(EnvironmentError, match="environment variables are not set"):
        _fetch_env_variables()


def test_upload_to_s3_uploads_all_files_with_keys(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>")
    assets = dist / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log(1)")

    mock_s3 = MagicMock()
    logger = logging.getLogger("test_upload_to_s3")

    _upload_to_s3(mock_s3, "my-bucket", dist, logger)

    assert mock_s3.upload_file.call_count == 2
    keys = {call.args[2] for call in mock_s3.upload_file.call_args_list}
    assert keys == {"index.html", "assets/app.js"}


def test_upload_to_s3_sets_content_type_when_known(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    html_file = dist / "index.html"
    html_file.write_text("<html></html>")

    mock_s3 = MagicMock()
    logger = logging.getLogger("test_upload_content_type")

    _upload_to_s3(mock_s3, "my-bucket", dist, logger)

    _, kwargs = mock_s3.upload_file.call_args
    assert kwargs["ExtraArgs"]["ContentType"] == "text/html"


def test_upload_to_s3_omits_extra_args_when_content_type_unknown(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "noextension").write_bytes(b"\x00\x01")

    mock_s3 = MagicMock()
    logger = logging.getLogger("test_upload_no_content_type")

    _upload_to_s3(mock_s3, "my-bucket", dist, logger)

    _, kwargs = mock_s3.upload_file.call_args
    assert kwargs["ExtraArgs"] == {}


def test_invalidate_cloudfront_creates_wildcard_invalidation():
    mock_cf = MagicMock()
    mock_cf.create_invalidation.return_value = {"Invalidation": {"Id": "INV123"}}
    logger = logging.getLogger("test_invalidate_cloudfront")

    _invalidate_cloudfront(mock_cf, "E1234567890", logger)

    mock_cf.create_invalidation.assert_called_once()
    kwargs = mock_cf.create_invalidation.call_args.kwargs
    assert kwargs["DistributionId"] == "E1234567890"
    assert kwargs["InvalidationBatch"]["Paths"]["Items"] == ["/*"]
    assert kwargs["InvalidationBatch"]["Paths"]["Quantity"] == 1


@patch("deploy_to_s3.deploy.boto3.client")
def test_main_success(mock_boto_client, tmp_path, monkeypatch, aws_env, caplog):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("hello")
    monkeypatch.setenv("DIST_PATH", str(dist))

    mock_s3 = MagicMock()
    mock_cf = MagicMock()
    mock_cf.create_invalidation.return_value = {"Invalidation": {"Id": "INV1"}}
    mock_boto_client.side_effect = lambda service, **_: (
        mock_s3 if service == "s3" else mock_cf
    )

    with caplog.at_level(logging.INFO):
        exit_code = main()

    assert exit_code == 0
    mock_s3.upload_file.assert_called_once()
    mock_cf.create_invalidation.assert_called_once()
    mock_boto_client.assert_any_call(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test-key-id",
        aws_secret_access_key="test-secret",
    )
    mock_boto_client.assert_any_call(
        "cloudfront",
        region_name="us-east-1",
        aws_access_key_id="test-key-id",
        aws_secret_access_key="test-secret",
    )


@patch("deploy_to_s3.deploy.boto3.client")
def test_main_returns_1_when_dist_missing(
    mock_boto_client, tmp_path, monkeypatch, aws_env, caplog
):
    monkeypatch.setenv("DIST_PATH", str(tmp_path / "missing"))

    with caplog.at_level(logging.ERROR):
        exit_code = main()

    assert exit_code == 1
    assert "Deploy failed with exception type: FileNotFoundError" in caplog.text
    mock_boto_client.assert_not_called()


@patch("deploy_to_s3.deploy.boto3.client")
def test_main_returns_1_when_aws_env_missing(
    mock_boto_client, tmp_path, monkeypatch, caplog
):
    dist = tmp_path / "dist"
    dist.mkdir()
    monkeypatch.setenv("DIST_PATH", str(dist))

    with caplog.at_level(logging.ERROR):
        exit_code = main()

    assert exit_code == 1
    assert "Deploy failed with exception type: OSError" in caplog.text
    mock_boto_client.assert_not_called()
