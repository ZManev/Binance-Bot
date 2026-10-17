FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY production_bot /app/production_bot
RUN python -m pip install --no-cache-dir --upgrade pip && python -m pip install --no-cache-dir pytest ccxt
RUN python -m pytest -q production_bot
EXPOSE 8080
RUN useradd --system --uid 10001 trading && mkdir -p /var/lib/trading && chown trading /var/lib/trading
USER trading
VOLUME ["/var/lib/trading"]
CMD ["python", "-m", "production_bot.service"]
