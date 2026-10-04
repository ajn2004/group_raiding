from functools import partial

import discord.ui
from discord import Bot
from discord.embeds import Embed
from discord.ext import commands
from discord.ui import Item

from app.casino.table import Table
from app.discord_bot.commands.modals import WipePredictionModal


class WipePredictionView(commands.Cog):
    def __init__(self, bot: Bot, ctx: commands.Context, table: Table):
        self.table = table
        self.book_type = "wipe_prediction"
        self.kill_bets = 0
        self.wipe_bets = 0
        self.ctx = ctx
        self.embed = Embed(
            title="Wipe Prediction",
            description="Bet on if you will wipe next pull!"
        )
        self.add_fields()

    def add_fields(self):
        self.embed.add_field(name="Kill", inline=True, value=str(self.kill_bets) + " PDT")
        self.embed.add_field(name="Wipe", inline=True, value=str(self.wipe_bets) + " PDT")

    async def send_view(self):
        await self.ctx.send(embed=self.embed, view=self.ButtonView())

    class ButtonView(discord.ui.View):

        def __init__(self, *items: Item):
            super().__init__(*items)
            button_win = discord.ui.Button(label='Kill!', style=discord.ButtonStyle.success)
            button_lose = discord.ui.Button(label='Wipe!', style=discord.ButtonStyle.danger)
            button_win.callback = partial(self.place_bet, value=True)
            button_lose.callback = partial(self.place_bet, value=False)
            self.add_item(button_win)
            self.add_item(button_lose)

        async def place_bet(self, interaction: discord.Interaction, value: bool):
            await interaction.response.send_modal(
                WipePredictionModal(
                    title="How much will you bet?",
                    boolean_value=value,
                    discord_id=interaction.user.id)
            )

    @commands.group()
    async def send_modal(self, ctx):
        print(ctx)
        pass


