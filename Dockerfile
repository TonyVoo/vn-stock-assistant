# The market service for the finwise backend: `docker build -t vn-market-api .` then run it with its environment
# (MARKET_API_KEY, ANTHROPIC_API_KEY or another LLM_PROVIDER; see README). Nothing secret is in the image.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt

COPY api/ api/
COPY src/ src/

# Not root: the one place the service writes is its price cache, so that folder is the user's.
RUN useradd --system --no-create-home app && mkdir -p data/cache && chown -R app data
USER app
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/v1/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8001"]
