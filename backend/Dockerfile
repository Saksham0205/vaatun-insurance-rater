FROM python:3.11.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY rate_cards ./rate_cards
COPY ocr_cache ./ocr_cache
ENV PYTHONUNBUFFERED=1 MALLOC_ARENA_MAX=2
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
