FROM python:3.10-slim

WORKDIR /app

# Install system dependencies (Git is often needed for some python packages)
RUN apt-get update && \
    apt-get install -y git && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# SPLIT INSTALLATION: Install heavy packages one by one to save RAM
RUN pip install --no-cache-dir pip setuptools wheel && \
    pip install --no-cache-dir pyrogram tgcrypto && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "app.py"]
