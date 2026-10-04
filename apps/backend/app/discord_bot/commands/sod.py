from discord import Bot
from app.db.models import Player
from discord.ext import commands
from datetime import datetime, timedelta
from .memes.loadMeme import Memes

# The strategy will be to call datetime.datetime.now(), subtract the known_reset variable in a time-delta, and observe the result
# Once the proper value for known_reset is determined, it should be fixed in perpetuity.
RESET_INTERVAL = 3


class SoDiscovery(commands.Cog):
    def __init__(self, bot: Bot, db_controller):
        self.bot = bot
        self.db_controller = db_controller
        # self.pdt_group = commands.Group(name='pdt', invoke_without_commands=True)

    @commands.group(name='sod', invoke_without_commands=True)
    async def sod_group(self, ctx: commands.Context) -> None:
        # tracker usage of command
        if player := self.db_controller.get_player(ctx.author.id):
            # track user engagement
            self.db_controller.track_usage(ctx)
        else:
            # Get patrick star meme for 'who are you?'
            await ctx.channel.send(file=Memes().getMeme('patrick'))
            return
                                      
    @sod_group.command(name='reset')
    async def check(self, ctx: commands.Context) -> None:
        if player := self.db_controller.get_player(ctx.author.id):
            known_reset = datetime(2023, 12, 21)
            elapsed_days = (datetime.now() - known_reset).days % RESET_INTERVAL
            days_to_next_reset = RESET_INTERVAL - elapsed_days
            next_reset_date = datetime.now() + timedelta(days=days_to_next_reset)
            await ctx.send(f"SoD Raids will reset in {days_to_next_reset} days on {next_reset_date.strftime('%Y-%m-%d')}.")
        await ctx.message.delete()

