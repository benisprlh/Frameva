# Optional Linux container. Native launchers are the supported Mac/Windows path.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FRAMEVA_DATA_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY frameva ./frameva
RUN python -m pip install --no-cache-dir . && useradd --create-home --uid 10001 frameva && mkdir /data && chown frameva /data
USER frameva
VOLUME ["/data"]
CMD ["frameva", "serve", "--no-open"]
