# BLACKFORGE - Docker image (for Koyeb / Fly.io / any container host)
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend includes the pre-built dashboard (backend/static/) - no Node needed.
COPY backend/ ./backend/

ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000

CMD ["python", "backend/app.py"]
