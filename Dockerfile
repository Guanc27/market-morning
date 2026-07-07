FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY extension/dist/ extension/dist/
COPY web/ web/
COPY docs/ docs/

ENV PYTHONPATH=/app/backend
ENV SAAS_MODE=1
ENV BACKEND_HOST=0.0.0.0
ENV BACKEND_PORT=8742
ENV DATABASE_PATH=/data/market_morning.db

EXPOSE 8742

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8742"]
