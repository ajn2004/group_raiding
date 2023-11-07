import discord
from discord.ext import commands

from app.db.controller import DBController
from app.discord_bot.commands.pdt import PiterToken
from app.discord_bot.commands.presyn import Presynapse
from app.discord_bot.commands.raid import Raid
# Intents
intents = discord.Intents.default()
intents.guild_messages = True
intents.messages = True
intents.members = True
intents.message_content =True
intents.guilds = True
permissions = discord.Permissions()
permissions.move_members = True
permissions.read_messages = True
permissions.add_reactions = True
permissions.use_application_commands = True
permissions.send_messages = True
permissions.view_channel = True
permissions.read_message_history = True
permissions.use_application_commands = True

# DB Connection
db_controller = DBController()

# Create an instance of a Bot object
bot = commands.Bot(command_prefix='!', description="A simple reply bot", intents=intents)

# Cogs
bot.add_cog(PiterToken(bot, db_controller))
bot.add_cog(Presynapse(bot, db_controller))
bot.add_cog(Raid(bot, db_controller))

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')

