from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

# We create the instances here, but do not link them to the app yet
db = SQLAlchemy()
login_manager = LoginManager()
