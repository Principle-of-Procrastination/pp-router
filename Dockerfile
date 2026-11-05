FROM python:3.12-slim AS gateway
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY deploy/requirements.lock /tmp/requirements.lock
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --index-url "$PIP_INDEX_URL" --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && groupadd --gid 10001 pprouter \
    && useradd --uid 10001 --gid 10001 --no-create-home pprouter \
    && mkdir /data && chown 10001:10001 /data
COPY pprouter/ pprouter/
COPY migrations/ migrations/
COPY alembic.ini ./
USER 10001:10001
EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health', timeout=3)"
CMD ["python", "-m", "uvicorn", "pprouter.main:app", "--host", "0.0.0.0", "--port", "4000", "--workers", "1", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips=*", "--timeout-graceful-shutdown", "200"]

FROM nginx:stable-alpine AS web
COPY frontend/dist/ /usr/share/nginx/html/
COPY deploy/pp-router-proxy.conf /etc/nginx/pp-router-proxy.conf
