import os
from flask import Flask
from extensions import db, login_manager
from routes import main, create_initial_data

# 1. instance_relative_config=True aktiviert den separaten "instance" Ordner für die DB
app = Flask(__name__, instance_relative_config=True)

# -- KONFIGURATION --

# Wir definieren den Pfad zum Instance-Ordner (für Debugging-Ausgaben)
# In Docker ist das standardmäßig /app/instance
print(f"DEBUG: Instance Path ist: {app.instance_path}")

# 2. Datenbank Pfad dynamisch setzen
# Die Datenbank landet jetzt in: /app/instance/inventory.db
db_filename = 'inventory.db'
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(app.instance_path, db_filename)}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Secret Key (Idealweise später über Environment Variable laden)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-bitte-aendern')

# Upload Konfiguration
# Wir nutzen app.root_path, um sicherzustellen, dass wir im App-Verzeichnis bleiben
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Max 16 MB

# -- INITIALISIERUNG --
db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'main.login'

app.register_blueprint(main)

if __name__ == '__main__':
    # 3. WICHTIG: Ordner erstellen, falls sie nicht existieren
    # Das verhindert Crashs, wenn man die App zum ersten Mal (oder ohne Docker Volume) startet.
    
    # Instance Ordner (für Datenbank)
    try:
        os.makedirs(app.instance_path)
        print(f"DEBUG: Instance Ordner erstellt: {app.instance_path}")
    except OSError:
        pass # Ordner existiert schon, alles gut

    # Upload Ordner (für Bilder)
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
        print(f"DEBUG: Upload Ordner erstellt: {app.config['UPLOAD_FOLDER']}")

    # Datenbank Initialisierung
    print(f"DEBUG: DB URI: {app.config['SQLALCHEMY_DATABASE_URI']}")

    with app.app_context():
        # Erstellt Tabellen nur, wenn die Datei inventory.db noch nicht existiert/leer ist
        db.create_all()
        
        # Admin User & Standard-Daten anlegen
        create_initial_data()
        
    # Start
    app.run(host='0.0.0.0', port=5000, debug=True)
