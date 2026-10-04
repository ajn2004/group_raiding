from functools import partial

import discord
from discord import Bot
from discord.ext import commands

from app.casino.casino import Casino as CasinoController
from app.db.controller import DBController
from app.discord_bot.views import DeadpoolView, WipePredictionView


class Casino(commands.Cog):
    def __init__(self, bot: Bot, db_controller: DBController):
        self.bot = bot
        self.db_controller = db_controller
        self.casino_controller = CasinoController()
        self.views = []

    @staticmethod
    def __parse_wcl_url(url: str) -> str:
        url_components = url.split('/')
        if url_components[2] != 'classic.warcraftlogs.com' or len(url_components) > 5:
            return ''
        return url_components[4]

    @commands.group(name='casino', invoke_without_commands=True)
    async def casino(self, ctx: commands.Context):
        print(ctx.subcommand_passed)

    @casino.command(name='create')
    async def create_table(self, ctx: commands.Context):
        message = ctx.message.content.split('!casino create')
        report_id = Casino.__parse_wcl_url(message[1])
        if report_id == '':
            await ctx.send(f"Invalid report URL....")
        else:
            results = self.casino_controller.create_table(report_id)
            if not results['success']:
                await ctx.send(results['message'])
                return
            deadpool_view = DeadpoolView(self.bot, ctx, results['table'])
            self.views.append(deadpool_view)
            wipe_prediction_view = WipePredictionView(self.bot, ctx, results['table'])
            self.views.append(wipe_prediction_view)
            await ctx.send(f"Report registered successfully! Welcome to the Casino!")
            await wipe_prediction_view.send_view()
            await deadpool_view.send_view()

    @casino.command(name='delete')
    async def delete_table(self, ctx: commands.Context) -> None:
        pass
