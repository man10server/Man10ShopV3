#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/docker-buildx.sh [options] (--push | --load)

Options:
  -i, --image NAME         Image name without tag (default: shojabon/man10shopv3)
  -t, --tag TAG            Tag to add (repeatable). If omitted, uses latest.
  -p, --platforms LIST     Target platforms (default: linux/amd64,linux/arm64)
      --builder NAME       buildx builder name (default: man10shopv3-builder)
  -f, --file PATH          Dockerfile path (default: Dockerfile)
  -c, --context PATH       Build context (default: .)
      --no-cache           Build without cache
      --push               Push multi-arch image to registry
      --load               Load image into local docker daemon (single platform only)
  -h, --help               Show this help

Examples:
  ./scripts/docker-buildx.sh --push -i shojabon/man10shopv3 -t latest
  ./scripts/docker-buildx.sh --load -p linux/arm64 -i man10shopv3-dev -t local
EOF
}

IMAGE="${IMAGE:-shojabon/man10shopv3}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
BUILDER="${BUILDER:-man10shopv3-builder}"
DOCKERFILE="${DOCKERFILE:-Dockerfile}"
CONTEXT="${CONTEXT:-.}"
PUSH=false
LOAD=false
NO_CACHE=false
TAGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--image)
      IMAGE="$2"
      shift 2
      ;;
    -t|--tag)
      TAGS+=("$2")
      shift 2
      ;;
    -p|--platforms)
      PLATFORMS="$2"
      shift 2
      ;;
    --builder)
      BUILDER="$2"
      shift 2
      ;;
    -f|--file)
      DOCKERFILE="$2"
      shift 2
      ;;
    -c|--context)
      CONTEXT="$2"
      shift 2
      ;;
    --push)
      PUSH=true
      shift
      ;;
    --load)
      LOAD=true
      shift
      ;;
    --no-cache)
      NO_CACHE=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ "${PUSH}" == true && "${LOAD}" == true ]]; then
  echo "Use either --push or --load, not both." >&2
  exit 1
fi

if [[ "${PUSH}" == false && "${LOAD}" == false ]]; then
  echo "Specify one: --push or --load" >&2
  exit 1
fi

if [[ "${LOAD}" == true && "${PLATFORMS}" == *,* ]]; then
  echo "--load supports only a single platform. Example: -p linux/amd64" >&2
  exit 1
fi

if ! docker buildx inspect "${BUILDER}" >/dev/null 2>&1; then
  docker buildx create --name "${BUILDER}" --use >/dev/null
else
  docker buildx use "${BUILDER}"
fi
docker buildx inspect --bootstrap >/dev/null

build_cmd=(docker buildx build --builder "${BUILDER}" --platform "${PLATFORMS}" -f "${DOCKERFILE}")

if [[ ${#TAGS[@]} -eq 0 ]]; then
  TAGS=("latest")
fi
for tag in "${TAGS[@]}"; do
  build_cmd+=(-t "${IMAGE}:${tag}")
done

if [[ "${NO_CACHE}" == true ]]; then
  build_cmd+=(--no-cache)
fi

if [[ "${PUSH}" == true ]]; then
  build_cmd+=(--push)
else
  build_cmd+=(--load)
fi

build_cmd+=("${CONTEXT}")

echo "Running: ${build_cmd[*]}"
"${build_cmd[@]}"
