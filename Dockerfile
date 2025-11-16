FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WAPPALYZER_BROWSERS=/app/browsers \
    PLAYWRIGHT_BROWSERS_PATH=/app/browsers \
    WAPPALYZER_DATA_DIR=/app/data/wappalyzer-data \
    WAPPALYZER_CAPTURE_DIR=/app/data/captures \
    WAPPALYZER_SCREENSHOT_DIR=/app/data/screenshots \
    WAPPALYZER_DB=/app/data/py_wappalyzer.db \
    PORT=8000

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        build-essential \
        libasound2 \
        libatk-bridge2.0-0 \
        libgtk-3-0 \
        libnss3 \
        libx11-xcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libgbm1 \
        libcairo2 \
        libpango-1.0-0 && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir -r requirements.txt

# Install Chromium for Patchright captures (optional at runtime, but handy).
RUN patchright install chromium

COPY . .

EXPOSE 8000

CMD ["uvicorn", "py_wappalyzer.web:app", "--host", "0.0.0.0", "--port", "8000"]
