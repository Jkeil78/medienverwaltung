import os
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# -- KONFIGURATION --
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///medien.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'dev-key-bitte-aendern'

# -- EXTENSIONS INIT --
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# -- DATENBANK MODELLE --

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True)
    users = db.relationship('User', backref='role', lazy='dynamic')

    def __repr__(self):
        return f'<Role {self.name}>'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def has_role(self, role_name):
        if self.role is None:
            return False
        return self.role.name == role_name

# -- LOGIN MANAGER --
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# -- SETUP HELPER --
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
            flash('Erfolgreich eingeloggt.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Login fehlgeschlagen. Bitte Daten prüfen.', 'error')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Du wurdest ausgeloggt.', 'info')
    return redirect(url_for('login'))

# -- ROUTE: PASSWORT ÄNDERN (NEU) --
@app.route('/profile/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        # 1. Prüfen, ob das alte Passwort stimmt
        if not current_user.check_password(current_password):
            flash('Das aktuelle Passwort ist falsch.', 'error')
            return redirect(url_for('change_password'))
        
        # 2. Prüfen, ob die neuen Passwörter übereinstimmen
        if new_password != confirm_password:
            flash('Die neuen Passwörter stimmen nicht überein.', 'error')
            return redirect(url_for('change_password'))
        
        # 3. Speichern
        current_user.set_password(new_password)
        db.session.commit()
        flash('Passwort erfolgreich geändert!', 'success')
        return redirect(url_for('index'))

    return render_template('change_password.html')


# -- ROUTEN: ADMIN --

@app.route('/admin')
@login_required
def admin_redirect():
    return redirect(url_for('admin_users'))

@app.route('/admin/users')
@login_required
def admin_users():
    if not current_user.has_role('Admin'):
        flash('Zugriff verweigert.', 'error')
        return redirect(url_for('index'))
    
    users = User.query.all()
    roles = Role.query.all()
    return render_template('admin_users.html', users=users, roles=roles)

@app.route('/admin/users/create', methods=['POST'])
@login_required
def user_create():
    if not current_user.has_role('Admin'):
        return redirect(url_for('index'))

    username = request.form.get('username')
    password = request.form.get('password')
    role_id = request.form.get('role_id')

    if User.query.filter_by(username=username).first():
        flash(f'Benutzer {username} existiert bereits.', 'error')
    else:
        new_user = User(username=username, role_id=role_id)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash(f'Benutzer {username} angelegt.', 'success')

    return redirect(url_for('admin_users'))

@app.route('/admin/users/delete/<int:user_id>')
@login_required
def user_delete(user_id):
    if not current_user.has_role('Admin'):
        return redirect(url_for('index'))
    
    user_to_delete = User.query.get_or_404(user_id)
    if user_to_delete.id == current_user.id:
        flash('Du kannst dich nicht selbst löschen!', 'error')
    else:
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f'Benutzer {user_to_delete.username} gelöscht.', 'success')

    return redirect(url_for('admin_users'))

# -- START --
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_initial_data()
    app.run(host='0.0.0.0', port=5000, debug=True)
