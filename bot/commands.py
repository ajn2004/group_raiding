from bot import bot
from app import app
from app.models import *
from discord import Interaction

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

admins = set([219443112567767041,189037705873588226,206240748692045836,245343112891858964])
@bot.group()
async def presyn(ctx):
    #Admin functions authorize usage
    if ctx.author.id in admins:
        print('sure')
    else:
        print('no')
