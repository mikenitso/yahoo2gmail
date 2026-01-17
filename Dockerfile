FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY migrations /app/migrations
COPY SPEC.md /app/SPEC.md
COPY TASKS.md /app/TASKS.md
COPY README.md /app/README.md

CMD ["python", "-m", "app.cmd.main"]
