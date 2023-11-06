from discord import player
from discord.ext import commands

class PiterToken(commands.Cog):
    def __init__(self, bot , db_controller):
        self.bot = bot
        self.db_controller = db_controller
        # self.pdt_group = commands.Group(name='pdt', invoke_without_commands=True)

    @commands.group(name='pdt', invoke_without_commands=True)
    async def pdt_group(self, ctx):
        # tracker usage of command
        print(f"{ctx.author.name} just used pdt")
        if player := self.db_controller.get_player(ctx.author.id):
            # track user engagement
            self.db_controller.track_usage(ctx)
        else:
            await ctx.send(f"Who are you people?")
                                      
    @pdt_group.command(name='check')
    async def check(self, ctx):
        if player := self.db_controller.get_player(ctx.author.id):
            await ctx.send(f"{player['name']} has a balance of {player['piter_death_tokens']} PiterDeathTokens.")
        await ctx.message.delete()

    @pdt_group.command(name='trade')
    async def trade(self,ctx):
        # Parse incoming trade command
        inCommand = ctx.message.content.split('!pdt trade')
        if inCommand[1] ==' ' or inCommand[1] == '' or inCommand[1] == ' ?':
            await ctx.send(f"To trade PDT use !pdt Player Amount")    
            await ctx.message.delete()
            return
        toPlayer, amount = inCommand[1][1:].split(' ')
        toPlayerId = int(toPlayer[2:-1])
        amount = int(amount)
        # Prevent negative Sends
        if amount <= 0:
            if player := self.db_controller.get_player(ctx.author.id):
                await ctx.send(f"You can't steal money from your friends {player['name']}")
            else:
                await ctx.send("You shouldn't be allowed to do any of this")
            return
        if not amount:
            await ctx.send(f"To trade PDT use !pdt Player Amount")    
            await ctx.message.delete()
            return

        trade_object = {
            'sender' : ctx.author.id,
            'receiver' : toPlayerId,
            'amount' : amount
            }
        
        result = self.db_controller.pdt_trade(trade_object)
        await ctx.send(result)
        await ctx.message.delete()

