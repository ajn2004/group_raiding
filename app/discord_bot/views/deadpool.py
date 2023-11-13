import math
from functools import partial

import discord
from discord import Bot
from discord.ext import commands
from discord.embeds import Embed
from discord.ui import Item

from app.casino.table import Table


class DeadpoolView(commands.Cog):
    def __init__(self, bot: Bot, ctx: commands.Context, table: Table):
        self.table = table
        self.actors = self.__parse_actors()
        self.book_type = "deadpool"
        self.ctx = ctx
        self.embed = Embed(
            title="Deadpool",
            description="Bet on which of your friends will die next!"
        )
        self.add_fields()

    def __parse_actors(self):
        return [{
            'gameID': actor['gameID'],
            'icon': actor['icon'],
            'name': actor['name'],
            'bets': 0
        } for actor in self.table.wcl_report['masterData']['actors']]

    def add_fields(self):
        actors_per_col = math.ceil(len(self.actors) / 3)
        field_one = ""
        start_index = 0
        for i in range(start_index, actors_per_col):
            field_one += f"{self.actors[i]['name']} - {self.actors[i]['bets']} PDT\n"
            start_index += 1
        self.embed.add_field(name="", inline=True, value=field_one)
        field_two = ""
        actors_per_col = start_index + actors_per_col
        for i in range(start_index, actors_per_col):
            field_two += f"{self.actors[i]['name']} - {self.actors[i]['bets']} PDT\n"
            start_index += 1
        self.embed.add_field(name="", inline=True, value=field_two)
        field_three = ""
        for i in range(start_index, len(self.actors)):
            field_three += f"{self.actors[i]['name']} - {self.actors[i]['bets']} PDT\n"
            start_index += 1
        self.embed.add_field(name="", inline=True, value=field_three)

    async def send_view(self):
        await self.ctx.send(embed=self.embed, view=self.ButtonView())

    class ButtonView(discord.ui.View):

        def __init__(self, *items: Item):
            super().__init__(*items)

        def place_bet(self):
            pass