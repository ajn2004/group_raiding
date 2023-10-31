# Synapticity Discord Bot

A bot to assist with discord actions in Presynaptic's discord

# Quickstart Installation
To get started with this codebase you need to have [python](https://www.python.org/downloads/) installed. If you're using WSL2 you can do this easily
```bash
sudo apt-get install python3
```
Download the codebase and install dependencies
```bash
git clone https://github.com/ajn2004/group_raiding
cd group_raiding
pip install -r requirements.txt
```
This will download the project to your machine and install the necessary libraries to run the code.

# Flask App
The [main.py](main.py) is the entry point for the [Flask](https://flask.palletsprojects.com/en/3.0.x/) arm of the project. It defines several functions to ease database creation and allows the running of the flask project from the project directory
```bash
export FLASK_APP=main.py
flask run
```
This tells flask to run main.py and allows you to access on your [local endpoint](http://127.0.0.1:5000). This is the starting point for all web page development if we were to go that route.

App behavior is defined in the subfolder, namely [models.py](app/models.py) and [routes.py](app/routes.py). These files define our database models and API behavior respectively. Changing [models.py](app/models.py) will have an impact on our database behavior, and changing [routes.py](app/routes.py) will alter how we serve that information to our users.

# Discord Bot
The [main_bot.py](main_bot.py) file is the discord bot. It can be run with a simple command
```bash
python3 main_bot.py
```
This will launch the bot to connect to the discord server and start hosting commands

## Discord Commands
Bot behavior is organized in the bot folder. Specifically [commands.py](bot/commands.py) defines various commands and their functions available to the server.

# Postgres Server
The postgres server can best be understood by studying the [models file](app/models.py). This is a basic relational database intended to model the guild environment. Accessing the server can be done through the [.env file](.env.example).
```
SQLALCHEMY_DATABASE_USER='YOUR_USER_NAME'
SQLALCHEMY_DATABASE_PASSWORD='YOUR_PASSWORD'
SQLALCHEMY_DATABASE_HOST='YOUR_DATABASE_ADDR'
SQLALCHEMY_DATABASE_PORT='YOUR_DATABASE_PORT'
SQLALCHEMY_DATABASE_DB='YOUR_DATABASE_NAME'
DISCORD_BOT_TOKEN='YOUR_DISCORD_BOT_API_TOKEN'
```
Update these values with your access information and the app should connect automatically.

Of course this requires you to be running a postgres server, or know how to access a running one.
