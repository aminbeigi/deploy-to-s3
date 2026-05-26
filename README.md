# deploy-to-s3

A reusable GitHub Action that uploads a built `dist/` directory to an S3 bucket and invalidates a CloudFront distribution.

Point it at your frontend build output - usually `dist/` from `npm run build` or similar. It uploads everything inside. Deploy fails fast if `dist/` is empty or missing `index.html` at the root, so a forgotten build step is caught before anything hits S3. You also need any JS, CSS, media, and other assets your app references.

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

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes. See [Deployment](#deployment) for notes on how to use the action in a live CI/CD pipeline.

### Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) - dependency management
- AWS credentials with permission to upload to your S3 bucket and create CloudFront invalidations (for local runs)

### Installing

1. Clone the repository:

```
git clone https://github.com/aminbeigi/deploy-to-s3.git
cd deploy-to-s3
```

1. Install dependencies:

```
uv sync
```

1. Copy the environment template (`.env` is gitignored):

```
cp .env_template .env
```

1. Edit `.env` with your AWS keys, region, bucket, and CloudFront distribution ID.
2. Run a local deploy (expects `dist/` at the repo root; set `DIST_PATH` if your build output is elsewhere):

```
uv run --env-file .env python -m deploy_to_s3
```

```
DIST_PATH=/path/to/dist uv run --env-file .env python -m deploy_to_s3
```

## Running the Tests

Automated tests use pytest. From the project root:

```
uv run pytest tests/
```

## Lint and Format

```
uv run ruff check --fix .
uv run ruff format .
```

## Deployment

Use this action from a consumer repository after your frontend (or static site) build step produces a `dist/` folder.

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

In the consumer repo, add these as repository secrets (Settings → Secrets and variables → Actions): 

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `AWS_S3_BUCKET_NAME`
- `CLOUDFRONT_DISTRIBUTION_ID`

## Authors

- Amin Beigi

## License

This project is licensed under the MIT License.  
See the [LICENSE.md](LICENSE.md) file for details.