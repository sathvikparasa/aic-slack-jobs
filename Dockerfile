FROM python:3.12-slim
WORKDIR /app
COPY jobwatch ./jobwatch
ENV PYTHONUNBUFFERED=1 STATE_DB=/data/jobwatch.db
VOLUME /data
CMD ["python", "-m", "jobwatch.main"]
