FROM python:3.12-slim

WORKDIR /app

# Optimize layer caching: deps first.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Non-root, production-minded.
RUN useradd --create-home --uid 1000 traderaig \
    && chown -R traderaig:traderaig /app
USER traderaig

CMD ["uvicorn", "operations.api:app", "--host", "0.0.0.0", "--port", "8000"]