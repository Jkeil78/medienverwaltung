import uuid
import os
import requests
import re
import io      
import qrcode
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify, send_file
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from extensions import db
# WICHTIG: AppSetting hier im Import ergänzt
from models import User, Role, Location, MediaItem, Collection, Track, AppSetting
from sqlalchemy import or_

main = Blueprint('main', __name__)

# -- HELPER --

def get_config_value(key, default=None):
    """Liest eine Einstellung aus der Datenbank"""
    try:
        setting = AppSetting.query.filter_by(key=key).first()
        if setting and setting.value:
            return setting.value
    except Exception:
        # Falls Tabelle noch nicht existiert oder DB Fehler
        pass
    return default

def set_config_value(key, value):
    """Schreibt eine Einstellung in die Datenbank"""
    setting = AppSetting.query.filter_by(key=key).first()
    if not setting:
        setting = AppSetting(key=key)
        db.session.add(setting)
    setting.value = value
    db.session.commit()

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_image(file):
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        new_filename = f"{uuid.uuid4().hex}.{ext}"
        path = os.path.join(current_app.config['UPLOAD_FOLDER'], new_filename)
        file.save(path)
        return new_filename
    return None

def download_remote_image(url):
    print(f"DEBUG: Starte Download von {url}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, stream=True, timeout=10)
        
        if response.status_code == 200:
            ext = 'jpg'
            if 'png' in url.lower(): ext = 'png'
            new_filename = f"{uuid.uuid4().hex}.{ext}"
            path = os.path.join(current_app.config['UPLOAD_FOLDER'], new_filename)
            with open(path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            print(f"DEBUG: Download erfolgreich: {new_filename}")
            return new_filename
        else:
            print(f"DEBUG: Download fehlgeschlagen. Status: {response.status_code}")
    except Exception as e:
        print(f"DEBUG: Exception beim Download: {e}")
    return None

def create_initial_data():
    if not Role.query.filter_by(name='Admin').first():
        db.session.add(Role(name='Admin'))
        db.session.add(Role(name='User'))
        db.session.commit()
    if not User.query.filter_by(username='admin').first():
        admin_role = Role.query.filter_by(name='Admin').first()
        admin = User(username='admin', role=admin_role)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
    if not Location.query.first():
        db.session.add(Location(name="Unsortiert"))
        db.session.commit()

def generate_inventory_number():
    year = datetime.now().year
    unique_part = str(uuid.uuid4())[:8].upper()
    return f"INV-{year}-{unique_part}"


# -- API ROUTE (DYNAMIC TOKEN) --

@main.route('/api/lookup/<barcode>')
@login_required
def api_lookup(barcode):
    print(f"DEBUG: API Lookup gestartet für {barcode}")
    
    data = {
        "success": False,
        "title": "",
        "author": "",
        "year": "",
        "description": "",
        "image_url": "" 
    }
    
    clean_isbn = ''.join(c for c in barcode if c.isdigit() or c.upper() == 'X')
    
    # ---------------------------------------------------------
    # SCHRITT 1: Google Books
    # ---------------------------------------------------------
    try:
        google_url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{clean_isbn}"
        res = requests.get(google_url, timeout=5)
        if res.status_code == 200:
            g_json = res.json()
            if "items" in g_json and len(g_json["items"]) > 0:
                print("DEBUG: Google Books hat Daten gefunden.")
                info = g_json["items"][0].get("volumeInfo", {})
                
                data["success"] = True
                data["title"] = info.get("title", "")
                data["author"] = ", ".join(info.get("authors", []))
                data["description"] = info.get("description", "")[:800]
                
                pub_date = info.get("publishedDate", "")
                if len(pub_date) >= 4: data["year"] = pub_date[:4]
                
                imgs = info.get("imageLinks", {})
                img_url = imgs.get("thumbnail") or imgs.get("smallThumbnail")
                if img_url:
                    if img_url.startswith("http://"):
                        img_url = img_url.replace("http://", "https://")
                    data["image_url"] = img_url
    except Exception as e:
        print(f"DEBUG: Google Error: {e}")

    # ---------------------------------------------------------
    # SCHRITT 2: Open Library
    # ---------------------------------------------------------
    if not data["success"] or not data["image_url"]:
        print("DEBUG: Starte OpenLibrary (Fallback)...")
        try:
            ol_url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{clean_isbn}&format=json&jscmd=data"
            res = requests.get(ol_url, timeout=5)
            if res.status_code == 200:
                result = res.json()
                if result:
                    book = list(result.values())[0]
                    if not data["success"]:
                        data["success"] = True
                        data["title"] = book.get("title", "")
                        data["author"] = ", ".join([a["name"] for a in book.get("authors", [])])
                        match = re.search(r'\d{4}', book.get("publish_date", ""))
                        if match: data["year"] = match.group(0)

                    if "cover" in book:
                        cover_url = book["cover"].get("large", "") or book["cover"].get("medium", "")
                        if cover_url:
                            data["image_url"] = cover_url
        except Exception as e:
            print(f"DEBUG: OpenLibrary Error: {e}")

    # ---------------------------------------------------------
    # SCHRITT 3: Discogs (Mit DB Token)
    # ---------------------------------------------------------
    discogs_token = get_config_value('discogs_token')
    
    # Nur ausführen wenn Token existiert UND wir noch Daten brauchen (oder explizit nachbessern wollen)
    # Hier: Fallback wenn bisher nichts gefunden wurde
    if not data["success"] and discogs_token:
        print("DEBUG: Starte Discogs Lookup...")
        try:
            headers = {
                "User-Agent": "HomeInventoryApp/1.0",
                "Authorization": f"Discogs token={discogs_token}"
            }
            discogs_url = "https://api.discogs.com/database/search"
            params = {"barcode": barcode, "type": "release", "per_page": 1}
            
            res = requests.get(discogs_url, headers=headers, params=params, timeout=5)
            
            if res.status_code == 200:
                d_json = res.json()
                results = d_json.get("results", [])
                
                if results:
                    print("DEBUG: Discogs hat Daten gefunden!")
                    item = results[0]
                    data["success"] = True
                    
                    full_title = item.get("title", "")
                    if " - " in full_title:
                        parts = full_title.split(" - ", 1)
                        data["author"] = parts[0].strip()
                        data["title"] = parts[1].strip()
                    else:
                        data["title"] = full_title
                        
                    data["year"] = item.get("year", "")
                    img_url = item.get("cover_image", "") or item.get("thumb", "")
                    if img_url: data["image_url"] = img_url
                        
                    genres = item.get("genre", []) + item.get("style", [])
                    data["description"] = "Genres: " + ", ".join(genres)
            elif res.status_code == 401:
                print("DEBUG: Discogs Token ungültig.")
        except Exception as e:
            print(f"DEBUG: Discogs Error: {e}")
    elif not discogs_token and not data["success"]:
        print("DEBUG: Kein Discogs Token in den Einstellungen hinterlegt.")

    return jsonify(data)


# -- QR-CODE --
@main.route('/qrcode_image/<inventory_number>')
def qrcode_image(inventory_number):
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(inventory_number)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        fp = io.BytesIO()
        img.save(fp, 'PNG')
        fp.seek(0)
        return send_file(fp, mimetype='image/png')
    except Exception as e:
        print(f"QR Error: {e}")
        return "Error", 500

# -- HAUPTROUTEN --

@main.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('main.login'))

    search_query = request.args.get('q')
    filter_category = request.args.get('category')
    filter_location = request.args.get('location')

    query = MediaItem.query

    if search_query:
        search_term = f"%{search_query}%"
        query = query.filter(or_(
            MediaItem.title.ilike(search_term),
            MediaItem.author_artist.ilike(search_term),
            MediaItem.inventory_number.ilike(search_term),
            MediaItem.barcode.ilike(search_term)
        ))

    if filter_category and filter_category != "":
        query = query.filter(MediaItem.category == filter_category)
    if filter_location and filter_location != "":
        query = query.filter(MediaItem.location_id == int(filter_location))

    items = query.order_by(MediaItem.created_at.desc()).all()
    locations = Location.query.all()
    locations_sorted = sorted(locations, key=lambda x: x.full_path)
    categories = ["Buch", "Film (DVD/BluRay)", "CD", "Vinyl/LP", "Videospiel", "Sonstiges"]

    return render_template('index.html', items=items, locations=locations_sorted, categories=categories)

@main.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and user.check_password(request.form.get('password')):
            login_user(user)
            return redirect(url_for('main.index'))
        flash('Login fehlgeschlagen.', 'error')
    return render_template('login.html')

@main.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.login'))

# -- SETTINGS ROUTE (NEU) --

@main.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if not current_user.has_role('Admin'):
        flash('Zugriff verweigert.', 'error')
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        token = request.form.get('discogs_token')
        set_config_value('discogs_token', token.strip() if token else "")
        flash('Einstellungen gespeichert.', 'success')
        return redirect(url_for('main.settings'))

    # Aktuelle Werte laden
    current_token = get_config_value('discogs_token', '')
    return render_template('settings.html', discogs_token=current_token)


# -- RESTLICHE ROUTEN --

@main.route('/admin/locations/edit/<int:loc_id>', methods=['GET', 'POST'])
@login_required
def location_edit(loc_id):
    if not current_user.has_role('Admin'): return redirect(url_for('main.index'))
    loc = Location.query.get_or_404(loc_id)
    possible_parents = Location.query.filter(Location.id != loc_id).all()
    sorted_parents = sorted(possible_parents, key=lambda x: x.full_path)
    if request.method == 'POST':
        loc.name = request.form.get('name')
        pid = request.form.get('parent_id')
        if pid and pid.strip():
            pid = int(pid)
            if pid == loc.id:
                flash('Fehler: Selbstbezug.', 'error')
                return redirect(url_for('main.location_edit', loc_id=loc.id))
            loc.parent_id = pid
        else:
            loc.parent_id = None
        db.session.commit()
        flash('Standort aktualisiert.', 'success')
        return redirect(url_for('main.admin_locations'))
    return render_template('location_edit.html', location=loc, all_locations=sorted_parents)

@main.route('/profile/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current = request.form.get('current_password')
        new = request.form.get('new_password')
        confirm = request.form.get('confirm_password')
        if not current_user.check_password(current):
            flash('Passwort falsch.', 'error')
        elif new != confirm:
            flash('Passwörter ungleich.', 'error')
        else:
            current_user.set_password(new)
            db.session.commit()
            flash('Gespeichert.', 'success')
            return redirect(url_for('main.index'))
    return render_template('change_password.html')

@main.route('/media/<int:item_id>')
@login_required
def media_detail(item_id):
    item = MediaItem.query.get_or_404(item_id)
    tracks = item.tracks.order_by(Track.position).all()
    return render_template('media_detail.html', item=item, tracks=tracks)

@main.route('/media/create', methods=['GET', 'POST'])
@login_required
def media_create():
    if request.method == 'POST':
        title = request.form.get('title')
        remote_url = request.form.get('remote_image_url')
        filename = None
        image_file = request.files.get('image')
        if image_file and image_file.filename != '':
            filename = save_image(image_file)
        elif remote_url and remote_url.strip() != '':
            filename = download_remote_image(remote_url)
        ry = request.form.get('release_year')
        ry = int(ry) if ry and ry.strip() else None
        new_item = MediaItem(
            inventory_number=generate_inventory_number(),
            title=title,
            category=request.form.get('category'),
            barcode=request.form.get('barcode') or None,
            author_artist=request.form.get('author_artist'),
            release_year=ry,
            description=request.form.get('description'),
            location_id=int(request.form.get('location_id') or 1),
            image_filename=filename,
            user_id=current_user.id
        )
        db.session.add(new_item)
        db.session.commit()
        flash(f'Medium "{title}" angelegt.', 'success')
        return redirect(url_for('main.index'))
    locations = Location.query.all()
    locations_sorted = sorted(locations, key=lambda x: x.full_path)
    categories = ["Buch", "Film (DVD/BluRay)", "CD", "Vinyl/LP", "Videospiel", "Sonstiges"]
    return render_template('media_create.html', locations=locations_sorted, categories=categories)

@main.route('/media/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
def media_edit(item_id):
    item = MediaItem.query.get_or_404(item_id)
    if request.method == 'POST':
        item.title = request.form.get('title')
        item.category = request.form.get('category')
        item.author_artist = request.form.get('author_artist')
        ry = request.form.get('release_year')
        item.release_year = int(ry) if ry and ry.strip() else None
        item.barcode = request.form.get('barcode') or None
        item.description = request.form.get('description')
        item.location_id = int(request.form.get('location_id') or 1)
        lent = request.form.get('lent_to')
        if lent and lent.strip():
            if not item.lent_to: item.lent_at = datetime.now()
            item.lent_to = lent
        else:
            item.lent_to = None
            item.lent_at = None
        image_file = request.files.get('image')
        remote_url = request.form.get('remote_image_url')
        new_filename = None
        if image_file and image_file.filename != '':
            new_filename = save_image(image_file)
        elif remote_url and remote_url.strip() != '':
            new_filename = download_remote_image(remote_url)
        if new_filename:
            item.image_filename = new_filename
        db.session.commit()
        flash('Gespeichert.', 'success')
        return redirect(url_for('main.media_detail', item_id=item.id))
    locations = Location.query.all()
    locations_sorted = sorted(locations, key=lambda x: x.full_path)
    categories = ["Buch", "Film (DVD/BluRay)", "CD", "Vinyl/LP", "Videospiel", "Sonstiges"]
    return render_template('media_edit.html', item=item, locations=locations_sorted, categories=categories)

@main.route('/media/delete/<int:item_id>')
@login_required
def media_delete(item_id):
    item = MediaItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('main.index'))

@main.route('/media/<int:item_id>/add_track', methods=['POST'])
@login_required
def track_add(item_id):
    item = MediaItem.query.get_or_404(item_id)
    t = request.form.get('title')
    p = request.form.get('position')
    d = request.form.get('duration')
    if t:
        db.session.add(Track(media_item_id=item.id, title=t, position=int(p) if p else 0, duration=d))
        db.session.commit()
    return redirect(url_for('main.media_detail', item_id=item.id))

@main.route('/track/delete/<int:track_id>')
@login_required
def track_delete(track_id):
    t = Track.query.get_or_404(track_id)
    mid = t.media_item_id
    db.session.delete(t)
    db.session.commit()
    return redirect(url_for('main.media_detail', item_id=mid))

@main.route('/admin')
@login_required
def admin_redirect(): return redirect(url_for('main.admin_users'))

@main.route('/admin/users')
@login_required
def admin_users():
    if not current_user.has_role('Admin'): return redirect(url_for('main.index'))
    return render_template('admin_users.html', users=User.query.all(), roles=Role.query.all())

@main.route('/admin/users/create', methods=['POST'])
@login_required
def user_create():
    if not current_user.has_role('Admin'): return redirect(url_for('main.index'))
    if not User.query.filter_by(username=request.form.get('username')).first():
        u = User(username=request.form.get('username'), role_id=request.form.get('role_id'))
        u.set_password(request.form.get('password'))
        db.session.add(u)
        db.session.commit()
    return redirect(url_for('main.admin_users'))

@main.route('/admin/users/delete/<int:user_id>')
@login_required
def user_delete(user_id):
    if not current_user.has_role('Admin'): return redirect(url_for('main.index'))
    u = User.query.get_or_404(user_id)
    if u.id != current_user.id:
        db.session.delete(u)
        db.session.commit()
    return redirect(url_for('main.admin_users'))

@main.route('/admin/locations')
@login_required
def admin_locations():
    if not current_user.has_role('Admin'): return redirect(url_for('main.index'))
    locations = Location.query.all()
    locations_sorted = sorted(locations, key=lambda x: x.full_path)
    return render_template('admin_locations.html', locations=locations_sorted)

@main.route('/admin/locations/create', methods=['POST'])
@login_required
def location_create():
    if not current_user.has_role('Admin'): return redirect(url_for('main.index'))
    pid = request.form.get('parent_id')
    db.session.add(Location(name=request.form.get('name'), parent_id=int(pid) if pid else None))
    db.session.commit()
    return redirect(url_for('main.admin_locations'))

@main.route('/admin/locations/delete/<int:loc_id>')
@login_required
def location_delete(loc_id):
    if not current_user.has_role('Admin'): return redirect(url_for('main.index'))
    l = Location.query.get_or_404(loc_id)
    if not l.children and l.items.count() == 0:
        db.session.delete(l)
        db.session.commit()
    return redirect(url_for('main.admin_locations'))
