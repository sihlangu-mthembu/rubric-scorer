FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rubric ./rubric

# Store the SQLite database on a mountable volume. Set SECRET_KEY when you run the container.
ENV RUBRIC_DB=/data/rubric.db
RUN mkdir -p /data
EXPOSE 8000
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 2 'rubric:create_app()'"]
