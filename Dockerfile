FROM python:3.9-slim

RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Gunicorn को सिर्फ 1 worker दो (फ्री प्लान में जरूरी)
CMD ["gunicorn --workers 1 --threads 2 --bind 0.0.0.0:10000 app:app --timeout 180
