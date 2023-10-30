from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv
import os
import secrets

load_dotenv()

# instantiate app
app = Flask(__name__, template_folder = 'templates')

# Set app secret keys and IDs
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET')  # Set the Flask secret key
app.config['CSRF_STATE'] = secrets.token_urlsafe(16)  # Generate a random CSRF token
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("SQLALCHEMY_DATABASE_URI") 
CORS(app)  # Enable CORS for the app

# register the routes blueprint
# app.register_blueprint(routes.bp)
from .models import db
db.init_app(app)

from . import routes
