from discord import Bot
import discord
from app.db.controller import DBController
from discord.ext import commands
from .memes.loadMeme import Memes, PDT
from .modals import pdtBettingModal
from functools import partial

class Gambling(commands.Cog):
    def __init__(self, bot: Bot, db_controller: DBController) -> None:
        self.bot = bot
        self.db_controller = db_controller
        # self.pdt_group = commands.Group(name='pdt', invoke_without_commands=True)

    @commands.group(name='bet', invoke_without_commands=True)
    async def bet_group(self, ctx: commands.Context) -> None:
        # tracker usage of command
        if player := self.db_controller.get_player(ctx.author.id):
            # track user engagement
            self.db_controller.track_usage(ctx)
        else:
            # Get patrick star meme for 'who are you?'
            await ctx.channel.send(file=Memes().getMeme('patrick'))
            return

    @bet_group.command(name='boss')
    async def guild_boss(self, ctx: commands.Context) -> None:
        inCommand = ctx.message.content.split(' ')
        if inCommand[-1] == 'boss':
            inCommand[-1] = 'Sindragosa'
        # this command will create a form allowing a user to bet some amount of PDT
        button_win = discord.ui.Button(label='Kill', style=discord.ButtonStyle.success)
        button_lose = discord.ui.Button(label='Wipe all Night!', style=discord.ButtonStyle.danger)
        
        async def button_callback(interaction: discord.Interaction, value: bool):
            await interaction.response.send_modal(pdtBettingModal(title="Enter an amount of " + PDT, boolean_value=value, discord_id = interaction.user.id))

        button_win.callback = partial(button_callback, value = True)
        button_lose.callback = partial(button_callback, value = False)

        view = discord.ui.View()
        view.add_item(button_win)
        view.add_item(button_lose)
        await ctx.send("Place your bets that we will kill " + inCommand[-1] + " on heroic this week!", view=view)
