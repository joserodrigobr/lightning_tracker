FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Volumes suggested for operational use
VOLUME ["/app/data", "/app/output", "/app/logs"]

CMD ["python", "main.py"]
