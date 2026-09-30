FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TA2KEED_DATA_DIR=/data PORT=8000
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000
CMD ["sh", "-c", "uvicorn ta2keed.server:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
