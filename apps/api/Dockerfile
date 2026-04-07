FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/apps/api


COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY apps/api /app/apps/api
RUN chmod +x /app/apps/api/docker/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/apps/api/docker/entrypoint.sh"]
