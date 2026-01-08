# Wir nutzen Python 3.9 als Basis
FROM python:3.9-slim

# Arbeitsverzeichnis im Container setzen
WORKDIR /app

# Abhängigkeiten installieren
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Den Rest des Codes kopieren
COPY . .

# Port freigeben (Flask Standard ist 5000)
EXPOSE 5000

# App starten
CMD ["python", "app.py"]
