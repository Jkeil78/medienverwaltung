import os
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# -- KONFIGURATION --
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///medien.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'dev-key-bitte-aendern' # In Produktion unbedingt ändern!

# -- EXTENSIONS INIT --
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Wohin wird man geleitet, wenn man nicht eingeloggt ist?

# -- DATENBANK MODELLE --

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True)
    # Beziehung zu Usern (One-to-Many)
    users = db.relationship('User', backref='role', lazy='dynamic')

    def __repr__(self):
        return f'<Role {self.name}>'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'))

    def set_password(self, password):
        """Erstellt einen sicheren Hash aus dem Passwort."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Prüft, ob das Passwort zum Hash passt."""
        return check_password_hash(self.password_hash, password)
    
    def has_role(self, role_name):
        """Hilfsfunktion für RBAC: Prüft, ob der User eine bestimmte Rolle hat."""
        if self.role is None:
            return False
        return self.role.name == role_name

# -- LOGIN MANAGER LOADER --
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# -- HILFSFUNKTIONEN (SETUP) --
def create_initial_data():
    """Erstellt Standard-Rollen und einen Admin-User, falls noch nicht vorhanden."""
    # Rollen anlegen
    if not Role.query.filter_by(name='Admin').first():
        db.session.add(Role(name='Admin'))
        db.session.add(Role(name='User'))
        db.session.commit()
        print("Standard-Rollen erstellt.")
    
    # Admin User anlegen
    if not User.query.filter_by(username='admin').first():
        admin_role = Role.query.filter_by(name='Admin').first()
        admin = User(username='admin', role=admin_role)
        admin.set_password('admin123') # Initiales Passwort
        db.session.add(admin)
        db.session.commit()
        print("User 'admin' mit Passwort 'admin123' erstellt.")

# -- ROUTEN --

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('Login fehlgeschlagen. Bitte Daten prüfen.')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Beispiel für eine geschützte Route (RBAC)
@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.has_role('Admin'):
        return "Zugriff verweigert: Nur für Admins!", 403
    return "Willkommen im Admin-Bereich"

# -- START --
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_initial_data() # Initialisiert Daten beim Start

    app.run(host='0.0.0.0', port=5000, debug=True)
