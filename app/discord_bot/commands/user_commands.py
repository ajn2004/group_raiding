from discord.ext import commands


class UserCommands(commands.Cog):
    def __init__(self, bot, db_controller):
        self.bot = bot
        self.db_controller = db_controller

    @commands.command(name='hello')
    async def hello(self, ctx):
        await ctx.send(f'Hello, {ctx.author.name}!')

    @commands.command()
    async def check(self, ctx):
        if player := self.db_controller.get_player(ctx.author.id):
            await ctx.send(f"{player['name']} has a balance of {player['piter_death_tokens']} PiterDeathTokens.")
        else:
            await ctx.send(f"Who are you people?")
        await ctx.message.delete()

