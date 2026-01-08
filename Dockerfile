FROM python:3.9-slim

# Verhindert, dass Python .pyc Dateien schreibt
ENV PYTHONDONTWRITEBYTECODE=1
# Zwingt Python, Ausgaben sofort ins Log zu schreiben (WICHTIG für Debugging)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "app.py"]
