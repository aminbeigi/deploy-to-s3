# Deploy to S3

I built this repo to automate updating my websites. I usually host them on AWS S3 as static React apps built with Vite, and I wanted a repeatable way to push a fresh build and refresh CloudFront without doing it by hand each time.

It is a reusable GitHub Action that uploads a built `dist/` directory to an S3 bucket and invalidates a CloudFront distribution.

Point it at your frontend build output — usually `dist/` from `npm run build` or similar (Vite’s default output directory is `dist/`). It uploads everything inside. You also need any JS, CSS, media, and other assets your app references.

A full frontend build often looks like:

```text
dist/
  index.html
  assets/
    index-a1b2c3.js
    index-d4e5f6.css
    logo.png
    hero.webp
  media/
    promo.mp4
  favicon.ico
```

## Run locally

Use this when developing the action itself or testing a deploy from your machine before wiring it into CI.

### Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) for dependency management
- AWS credentials with permission to upload to your S3 bucket and create CloudFront invalidations

### Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/aminbeigi/deploy-to-s3.git
   cd deploy-to-s3
   ```

2. Install dependencies:

   ```bash
   uv sync
   ```

3. Copy the environment template (`.env` is gitignored):

   ```bash
   cp .env_template .env
   ```

4. Edit `.env` with your AWS keys, region, bucket, and CloudFront distribution ID.

### Deploy

The command expects `dist/` at the repo root. Set `DIST_PATH` if your build output lives elsewhere.

```bash
uv run --env-file .env python -m deploy_to_s3
```

```bash
DIST_PATH=/path/to/dist uv run --env-file .env python -m deploy_to_s3
```

### Dry run

Pass `--dry-run` to validate configuration and log exactly which files would be uploaded without making any AWS calls. Useful for checking your build output before a real deploy.

```bash
uv run --env-file .env python -m deploy_to_s3 --dry-run
```

```bash
DIST_PATH=/path/to/dist uv run --env-file .env python -m deploy_to_s3 --dry-run
```

### Development

Run tests:

```bash
uv run pytest tests/
```

Lint and format:

```bash
uv run ruff check --fix .
uv run ruff format .
```

## Run as a GitHub Action

Use this from a consumer repository after your frontend build step produces a `dist/` folder.

### Workflow example

In your repo's workflow file (e.g. `.github/workflows/pipeline.yml`):

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: npm ci && npm run build   # produces dist/

      - uses: aminbeigi/deploy-to-s3@main
        with:
          dist-path: dist
          aws-region: ${{ secrets.AWS_REGION }}
          s3-bucket: ${{ secrets.AWS_S3_BUCKET_NAME }}
          cloudfront-distribution-id: ${{ secrets.CLOUDFRONT_DISTRIBUTION_ID }}
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

### Repository secrets

In the consumer repo, add these under **Settings → Secrets and variables → Actions**:

| Secret | Purpose |
|--------|---------|
| `AWS_ACCESS_KEY_ID` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `AWS_REGION` | AWS region (e.g. `us-east-1`) |
| `AWS_S3_BUCKET_NAME` | Target S3 bucket |
| `CLOUDFRONT_DISTRIBUTION_ID` | CloudFront distribution to invalidate after upload |

### Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `dist-path` | No | `dist` | Path to built assets, relative to the consumer repo root |
| `aws-region` | Yes | — | AWS region |
| `s3-bucket` | Yes | — | S3 bucket name |
| `cloudfront-distribution-id` | Yes | — | CloudFront distribution ID |
| `aws-access-key-id` | Yes | — | AWS access key ID |
| `aws-secret-access-key` | Yes | — | AWS secret access key |

## Authors

- Amin Beigi

## License

This project is licensed under the MIT License.  
See the [LICENSE.md](LICENSE.md) file for details.
