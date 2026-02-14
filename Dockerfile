FROM python:3.9-slim-buster

WORKDIR /man10shopv3

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev

COPY . .

CMD [".venv/bin/python", "main.py"]
