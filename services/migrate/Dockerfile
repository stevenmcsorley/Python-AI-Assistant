FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY services/migrate/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/migrate/migrate.py /app/migrate.py
COPY migrations /app/migrations

CMD ["python", "/app/migrate.py"]
