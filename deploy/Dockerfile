FROM python:3.11-slim-bookworm
WORKDIR /app
COPY deploy/requirements-web.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY web ./web
COPY config ./config
COPY mbt_paths.py .
ENV PYTHONPATH=/app
ENV MBT_DATA_ROOT=/data
ENV PORT=8080
EXPOSE 8080
CMD ["python", "backend/app.py"]
