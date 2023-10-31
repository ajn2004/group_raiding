from flask import Flask
from flask_cors import CORS
from flask_migrate import Migrate
from dotenv import load_dotenv
import os
import secrets

load_dotenv()

# instantiate app
app = Flask(__name__, template_folder = 'templates')

# Set app secret keys and IDs
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET')  # Set the Flask secret key
app.config['CSRF_STATE'] = secrets.token_urlsafe(16)  # Generate a random CSRF token

# Build database uri from .env file
sql_uri =  "postgresql://" + str(os.getenv("SQLALCHEMY_DATABASE_USER")) + ":" + str(os.getenv("SQLALCHEMY_DATABASE_PASSWORD")) + "@" + str(os.getenv("SQLALCHEMY_DATABASE_HOST")) + ":" + str(os.getenv("SQLALCHEMY_DATABASE_PORT")) + "/" + str(os.getenv("SQLALCHEMY_DATABASE_DB"))
app.config['SQLALCHEMY_DATABASE_URI'] = sql_uri
CORS(app)  # Enable CORS for the app

# register the routes blueprint
# app.register_blueprint(routes.bp)
from .models import db
db.init_app(app)
migrate = Migrate(app, db)
from . import routes
