import os
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# Konfiguration
# Die Datenbank wird im Ordner 'instance' gespeichert
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///medien.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'dev-key-bitte-aendern'

# Datenbank Initialisierung
db = SQLAlchemy(app)

# -- DATENBANK MODELLE (Platzhalter) --
# Hier definieren wir gleich im nächsten Schritt die Tabellen

# -- ROUTEN --

@app.route('/')
def index():
    return render_template('index.html')

# -- START --
if __name__ == '__main__':
    # Erstellt die Datenbank Tabellen, falls sie nicht existieren
    with app.app_context():
        db.create_all()
    
    # Startet den Server, erreichbar unter 0.0.0.0 (für Docker wichtig)
    app.run(host='0.0.0.0', port=5000, debug=True)
