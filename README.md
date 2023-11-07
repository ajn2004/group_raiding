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
poetry install
```
This will download the project to your machine and install the necessary libraries to run the code.

# Discord Bot
The [main.py](main.py) file is entry point for the discord bot. It can be run with a simple command
```bash
python3 main.py
```
This will launch the bot to connect to the discord server and start hosting commands


# Postgres Server
The postgres server can best be understood by studying the [models](app/db/models). This is a basic relational database intended to model the guild environment. Accessing the server can be done through the [.env file](.env.example).
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
