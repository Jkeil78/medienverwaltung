import os
import shutil
import zipfile
import datetime
import time
from flask import current_app
from extensions import db

def create_backup_zip():
    """
    Creates a ZIP archive containing the database and the upload folder.
    Returns the path to the ZIP file.
    """
    # 1. Determine paths
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    
    if 'sqlite' not in db_uri:
        raise Exception("Backup currently only works with SQLite databases.")

    # Extract path from URI
    if '///' in db_uri:
        db_path = db_uri.split('///')[1]
    else:
        db_path = 'inventory.db'

    # If the path in config is absolute (which it is in the new app.py), use it directly.
    # If it is relative, look in the instance folder.
    if not os.path.isabs(db_path):
        possible_path = os.path.join(current_app.instance_path, db_path)
        if not os.path.exists(possible_path):
            possible_path = os.path.join(current_app.root_path, db_path)
        db_path = possible_path

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found at: {db_path}")

    upload_folder = current_app.config['UPLOAD_FOLDER']
    
    # 2. Generate filename for backup
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_filename = f"backup_inventory_{timestamp}.zip"
    backup_path = os.path.join(current_app.instance_path, backup_filename)
    
    if not os.path.exists(current_app.instance_path):
        os.makedirs(current_app.instance_path)

    # 3. Create Zip
    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # We always save the DB as 'database.sqlite' in the zip, regardless of its original name
        zipf.write(db_path, arcname='database.sqlite')
        
        if os.path.exists(upload_folder):
            for root, dirs, files in os.walk(upload_folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    # Relative path in Zip (e.g. uploads/image.jpg)
                    arcname = os.path.join('uploads', os.path.relpath(file_path, upload_folder))
                    zipf.write(file_path, arcname=arcname)
    
    return backup_path, backup_filename

def restore_backup_zip(zip_filepath):
    """
    Restores database and images from a ZIP.
    Uses copyfile instead of move to avoid Docker mount problems (Errno 16).
    """
    # 1. Determine paths
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'sqlite' not in db_uri:
        raise Exception("Restore only possible with SQLite.")
    
    if '///' in db_uri:
        db_file_name = db_uri.split('///')[1]
    else:
        db_file_name = 'inventory.db'

    # Determine target path (Preference: Instance Path)
    if not os.path.isabs(db_file_name):
         target_db_path = os.path.join(current_app.instance_path, db_file_name)
    else:
        # If the path in config is absolute (new app.py does this), use it directly
        target_db_path = db_file_name

    upload_folder = current_app.config['UPLOAD_FOLDER']

    # 2. Disconnect connections
    db.session.remove()
    db.engine.dispose()
    
    # Short pause for file locks
    time.sleep(0.5)

    # 3. Check and extract Zip
    with zipfile.ZipFile(zip_filepath, 'r') as zipf:
        if 'database.sqlite' not in zipf.namelist():
            raise Exception("Invalid backup archive: 'database.sqlite' missing.")
        
        # Create Temp Folder
        temp_extract_path = os.path.join(current_app.instance_path, 'temp_restore')
        if os.path.exists(temp_extract_path):
            shutil.rmtree(temp_extract_path)
        os.makedirs(temp_extract_path)
        
        # Extract database temporarily
        zipf.extract('database.sqlite', temp_extract_path)
        extracted_db = os.path.join(temp_extract_path, 'database.sqlite')
        
        # A) Restore database
        
        # Backup of current DB (if possible)
        if os.path.exists(target_db_path):
            try:
                shutil.copyfile(target_db_path, target_db_path + ".bak")
            except OSError:
                print("Warning: Could not create .bak of the database.")

        # Overwrite new DB (copyfile keeps inodes/mounts)
        try:
            shutil.copyfile(extracted_db, target_db_path)
        except OSError as e:
            raise Exception(f"Database file is locked. Please restart container. Error: {e}")

        # B) Extract images
        # We do NOT delete the upload folder beforehand, but only overwrite/add.
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
            
        for member in zipf.namelist():
            if member.startswith('uploads/'):
                filename = os.path.basename(member)
                if not filename: continue 
                
                source = zipf.open(member)
                target_path = os.path.join(upload_folder, filename)
                
                with source, open(target_path, "wb") as target:
                    shutil.copyfileobj(source, target)

        # Clean up Temp
        shutil.rmtree(temp_extract_path)
        
    return True
