import os
import shutil
import zipfile
import datetime
from flask import current_app
from extensions import db

def create_backup_zip():
    """
    Erstellt ein ZIP-Archiv mit der Datenbank und dem Upload-Ordner.
    Gibt den Pfad zur ZIP-Datei zurück.
    """
    # 1. Pfade ermitteln
    # Wir gehen davon aus, dass die DB SQLite ist und im instance-Ordner oder Root liegt
    # SQLALCHEMY_DATABASE_URI ist z.B. 'sqlite:///inventory.db' oder 'sqlite:////absolute/path/inventory.db'
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    
    if 'sqlite' not in db_uri:
        raise Exception("Backup funktioniert derzeit nur mit SQLite Datenbanken.")

    # Pfad zur DB-Datei extrahieren
    if '///' in db_uri:
        db_path = db_uri.split('///')[1]
    else:
        # Fallback, falls URI anders aufgebaut ist
        db_path = 'inventory.db'

    # Wenn der Pfad relativ ist, müssen wir ihn absolut machen (relativ zum instance path oder root)
    if not os.path.isabs(db_path):
        # Versuch 1: Im Instance Folder
        possible_path = os.path.join(current_app.instance_path, db_path)
        if not os.path.exists(possible_path):
            # Versuch 2: Im App Root
            possible_path = os.path.join(current_app.root_path, db_path)
        db_path = possible_path

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Datenbankdatei nicht gefunden unter: {db_path}")

    upload_folder = current_app.config['UPLOAD_FOLDER']
    
    # 2. Dateinamen für Backup generieren
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_filename = f"backup_inventory_{timestamp}.zip"
    backup_path = os.path.join(current_app.instance_path, backup_filename)
    
    # Sicherstellen, dass instance folder existiert
    if not os.path.exists(current_app.instance_path):
        os.makedirs(current_app.instance_path)

    # 3. Zip erstellen
    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Datenbank hinzufügen (als 'database.sqlite' im Zip)
        zipf.write(db_path, arcname='database.sqlite')
        
        # Uploads hinzufügen
        if os.path.exists(upload_folder):
            for root, dirs, files in os.walk(upload_folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    # Relativer Pfad im Zip (z.B. uploads/bild.jpg)
                    arcname = os.path.join('uploads', os.path.relpath(file_path, upload_folder))
                    zipf.write(file_path, arcname=arcname)
    
    return backup_path, backup_filename

def restore_backup_zip(zip_filepath):
    """
    Stellt Datenbank und Bilder aus einem ZIP wieder her.
    ACHTUNG: Überschreibt existierende Daten!
    """
    # 1. Pfade ermitteln (gleiche Logik wie oben)
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'sqlite' not in db_uri:
        raise Exception("Restore nur mit SQLite möglich.")
    
    if '///' in db_uri:
        db_file_name = db_uri.split('///')[1]
    else:
        db_file_name = 'inventory.db'

    # Ziel-Pfad der DB bestimmen
    # Wir nehmen an, sie liegt dort, wo Flask sie erwartet (instance oder root)
    # Am sichersten: current_app.instance_path nutzen, wenn es ein relativer Pfad ist
    if not os.path.isabs(db_file_name):
         target_db_path = os.path.join(current_app.instance_path, db_file_name)
         # Fallback Check: Wenn sie im Root liegt
         if not os.path.exists(target_db_path) and os.path.exists(os.path.join(current_app.root_path, db_file_name)):
             target_db_path = os.path.join(current_app.root_path, db_file_name)
    else:
        target_db_path = db_file_name

    upload_folder = current_app.config['UPLOAD_FOLDER']

    # 2. Verbindungen trennen (Wichtig bei SQLite, um File Lock Fehler zu vermeiden)
    db.session.remove()
    db.engine.dispose()

    # 3. Zip prüfen und entpacken
    with zipfile.ZipFile(zip_filepath, 'r') as zipf:
        # Checken ob database.sqlite drin ist
        if 'database.sqlite' not in zipf.namelist():
            raise Exception("Ungültiges Backup-Archiv: 'database.sqlite' fehlt.")
        
        # A) Datenbank extrahieren
        # Wir extrahieren sie temporär und verschieben sie dann
        temp_extract_path = os.path.join(current_app.instance_path, 'temp_restore')
        if os.path.exists(temp_extract_path):
            shutil.rmtree(temp_extract_path)
        os.makedirs(temp_extract_path)
        
        zipf.extract('database.sqlite', temp_extract_path)
        
        # Die extrahierte DB an den echten Ort verschieben (überschreiben)
        extracted_db = os.path.join(temp_extract_path, 'database.sqlite')
        
        # Backup der aktuellen DB machen (Safety First)
        if os.path.exists(target_db_path):
            shutil.move(target_db_path, target_db_path + ".bak")
            
        shutil.move(extracted_db, target_db_path)

        # B) Bilder extrahieren
        # Ordner uploads leeren (optional, um "tote" Bilder zu löschen) oder überschreiben/ergänzen
        # Wir entscheiden uns für: Ergänzen/Überschreiben
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
            
        for member in zipf.namelist():
            if member.startswith('uploads/'):
                # Pfad strippen (uploads/ wegnehmen)
                filename = os.path.basename(member)
                if not filename: continue # Ordner überspringen
                
                source = zipf.open(member)
                target = open(os.path.join(upload_folder, filename), "wb")
                with source, target:
                    shutil.copyfileobj(source, target)

        # Temp aufräumen
        shutil.rmtree(temp_extract_path)
        
    return True
