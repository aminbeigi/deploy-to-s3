"""Command-line interface for deploy-to-s3.

Parses ``sys.argv`` and returns a typed :class:`argparse.Namespace` for use by
the :func:`~deploy_to_s3.deploy.main` entry point.
"""

import argparse


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for deploy-to-s3.

    Returns:
        A configured :class:`argparse.ArgumentParser` instance.
    """
    parser = argparse.ArgumentParser(
        description="Upload a dist/ directory to S3 and invalidate CloudFront."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and log planned actions without making any AWS calls.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list to parse. Defaults to ``sys.argv[1:]`` when ``None``.

    Returns:
        Parsed arguments as a :class:`argparse.Namespace` with a ``dry_run`` attribute.
    """
    return _build_parser().parse_args(argv)
