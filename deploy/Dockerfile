FROM python:3.11-slim-bookworm
WORKDIR /app
COPY deploy/requirements-web.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY web ./web
RUN mkdir -p ./config
COPY config/__init__.py config/deploy.py config/web_config.json ./config/
COPY mbt_paths.py runtime_security.py roles.py version.json ./
ENV PYTHONPATH=/app
ENV MBT_DATA_ROOT=/data
ENV MBT_ENV=production
ENV PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)"
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "backend.app:create_app()"]
