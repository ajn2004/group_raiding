from bot import bot
from app import app
from app.models import *
from discord import Interaction
from discord.ext import commands

# A command that responds with a personalized message
@bot.command(name='hello')
async def hello(ctx):
    await ctx.send(f'Hello, {ctx.author.name}!')


@bot.group(invoke_without_command=True)
async def pdt(ctx):
    await ctx.send("subcommand not found")
    pass

# @bot.add_command(name="pdt", description="Check your PiterDeathToken Balance")
@pdt.command()
async def check(ctx):
    with app.app_context():
        player = Player.query.filter_by(discord_id = ctx.author.id).first()
    if player:
        await ctx.send(f"You have a balance of {player.piter_death_tokens} PiterDeathTokens.")
    else:
        await ctx.send(f"Who are you people?")
