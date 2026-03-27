#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version>"
  echo "Example: $0 0.1.0"
  exit 1
fi

IMAGE="ghcr.io/man10server/man10shopv3"
TAG="v${VERSION}"

echo "==> Building and pushing ${IMAGE}:${VERSION} (linux/amd64,linux/arm64)"

BUILDER="man10shop-multiarch"
if ! docker buildx inspect "$BUILDER" &>/dev/null; then
  docker buildx create --name "$BUILDER" --use
else
  docker buildx use "$BUILDER"
fi

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag "${IMAGE}:${VERSION}" \
  --tag "${IMAGE}:latest" \
  --push \
  .

echo "==> Pushed ${IMAGE}:${VERSION} and ${IMAGE}:latest"

if git rev-parse "$TAG" &>/dev/null; then
  echo "==> Git tag ${TAG} already exists, skipping"
else
  git tag "$TAG"
  git push origin "$TAG"
  echo "==> Created and pushed git tag ${TAG}"
fi

if gh release view "$TAG" &>/dev/null; then
  echo "==> GitHub release ${TAG} already exists, skipping"
else
  gh release create "$TAG" --title "${TAG}" --generate-notes
  echo "==> Created GitHub release ${TAG}"
fi

echo "==> Done! Release ${VERSION} complete."
