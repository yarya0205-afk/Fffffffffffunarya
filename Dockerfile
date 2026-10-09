FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg fonts-dejavu-core fonts-liberation fonts-noto \
    build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p downloads fonts hosted_files host_logs
EXPOSE 10000
CMD ["python", "ARYA.py"]
