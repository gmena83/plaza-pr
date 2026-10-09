FROM python:3.12-slim

WORKDIR /app

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY normalize/ normalize/
COPY scrapers/common.py scrapers/common.py
COPY scrapers/__init__.py scrapers/__init__.py
COPY api/ api/
COPY config/ config/

EXPOSE 8200
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8200"]
