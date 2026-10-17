FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY production_bot /app/production_bot
COPY frontend /app/frontend
RUN python -m pip install --no-cache-dir --upgrade pip && python -m pip install --no-cache-dir pytest ccxt fastapi uvicorn
RUN python -m pytest -q production_bot
EXPOSE 8080
RUN useradd --system --uid 10001 trading && mkdir -p /var/lib/trading && chown -R trading:trading /var/lib/trading /app
USER trading
VOLUME ["/var/lib/trading"]
CMD ["uvicorn", "production_bot.dashboard_api:app", "--host", "0.0.0.0", "--port", "8080"]
