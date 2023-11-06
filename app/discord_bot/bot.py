import discord
from discord.ext import commands

from app.db.controller import DBController
from app.discord_bot.commands.pdt import PiterToken

# Intents
intents = discord.Intents.default()
intents.message_content = True

# DB Connection
db_controller = DBController()

# Create an instance of a Bot object
bot = commands.Bot(command_prefix='!', description="A simple reply bot", intents=intents)

# Cogs
bot.add_cog(PiterToken(bot, db_controller))


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')

