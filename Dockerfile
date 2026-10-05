FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir --upgrade pip && python -m pip install --no-cache-dir pytest ccxt
RUN python -m pytest -q production_bot
EXPOSE 8080
CMD ["python", "-m", "production_bot.deployment_health"]
