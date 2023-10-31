import discord
from app.models import *
from app import app
import os
from discord.ext import commands
# from discord.commands import slash_commands

# defining intents
intents = discord.Intents.default()
intents.guild_messages = True
intents.messages = True
intents.message_content =True
intents.guilds = True
permissions = discord.Permissions()
permissions.move_members = True
permissions.read_messages = True
permissions.use_application_commands = True
permissions.send_messages = True
permissions.view_channel = True
permissions.read_message_history = True
permissions.use_application_commands = True



# Create an instance of a Bot object
bot = commands.Bot(command_prefix='!', description="A simple reply bot", intents=intents, permissions=permissions)

# An event that prints to the console when the bot is ready
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')

# A command that responds with a personalized message
@bot.command(name='hello')
async def hello(ctx):
    with app.app_context():
        sched = Schedule.query.filter_by(player_id=1).first()
        sched.printWeek()
    await ctx.send(f'Hello, {ctx.author.name}!')

@bot.event
async def on_message(message):
    if message.channel.name == "bots":
        if message.author.id != 1168641939873202196:
            with app.app_context():
                player = Player.query.filter_by(discord_id = message.author.id).first()
            print(player.name)
            print(message.author.name)
            await message.channel.send(f"Hey , did you say '{message.content}'?")
    

# Run the bot with your token
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
