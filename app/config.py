from dotenv import load_dotenv
import os
load_dotenv()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
USERNAME = os.getenv("SQLALCHEMY_DATABASE_USER")
PASSWORD = os.getenv("SQLALCHEMY_DATABASE_PASSWORD")
DB_SERVER = str(os.getenv("SQLALCHEMY_DATABASE_HOST")) + ":" + str(os.getenv("SQLALCHEMY_DATABASE_PORT"))
DB_NAME = os.getenv("SQLALCHEMY_DATABASE_DB")
