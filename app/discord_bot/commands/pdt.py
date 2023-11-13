from discord import Bot
from app.db.models import Player
from discord.ext import commands
from .memes.loadMeme import Memes


class PiterToken(commands.Cog):
    def __init__(self, bot: Bot, db_controller):
        self.bot = bot
        self.db_controller = db_controller
        # self.pdt_group = commands.Group(name='pdt', invoke_without_commands=True)

    @commands.group(name='pdt', invoke_without_commands=True)
    async def pdt_group(self, ctx: commands.Context) -> None:
        # tracker usage of command
        if player := self.db_controller.get_player(ctx.author.id):
            # track user engagement
            self.db_controller.track_usage(ctx)
        else:
            # Get patrick star meme for 'who are you?'
            await ctx.channel.send(file=Memes().getMeme('patrick'))
            return
                                      
    @pdt_group.command(name='check')
    async def check(self, ctx: commands.Context) -> None:
        if player := self.db_controller.get_player(ctx.author.id):
            await ctx.send(f"{player['name']} has a balance of {player['piter_death_tokens']} PiterDeathTokens.")
        await ctx.message.delete()

    @pdt_group.command(name='trade')
    async def trade(self,ctx: commands.Context) -> None:
        # Parse incoming trade command
        inCommand = ctx.message.content.split('!pdt trade')
        if inCommand[1] ==' ' or inCommand[1] == '' or inCommand[1] == ' ?':
            await ctx.send(f"To trade PDT use !pdt Player Amount")    
            await ctx.message.delete()
            return

        splitString = inCommand[1][1:].split(' ')
        toPlayer = splitString[0]
        amount = splitString[-1]
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

        if ctx.author.id == toPlayerId:
            await ctx.send(f"{ctx.author.nick} tried trading themselves {amount} <:pdt:1009279728366137425>.... good work")
            await ctx.message.channel.send(file=Memes().getMeme('obama'))
            return
        trade_object = {
            'sender' : ctx.author.id,
            'receiver' : toPlayerId,
            'amount' : amount
            }
        
        result = self.db_controller.pdt_trade(trade_object)
        await ctx.send(result)
        await ctx.message.delete()

    @pdt_group.command(name='top')
    async def top(self, ctx: commands.Context) -> None:
        inCommand = ctx.message.content.split('!pdt top')
        await ctx.message.delete()
        if inCommand[1] == ' ' or inCommand[1] == '':
            n = 5
        else:
            try:
                n = int(inCommand[1])
            except:
                await ctx.send('use `!pdt top n` to see the top N players')
                n = 5
        leader_boards = self.db_controller.get_pdt_leaderboards(n)
        outString = "```\n"
        amounts = {'hold':[],'earn':[],'spend':[]}
        for i in range(n):
            amounts['hold'].append(leader_boards['hold'][i].piter_death_tokens)
            amounts['earn'].append(leader_boards['earn'][i].tokens_received)
            amounts['spend'].append(leader_boards['spend'][i].tokens_spent)
        outString += self.buildScoreTable(leader_boards['hold'],amounts['hold'],'Holders')
        outString += "\n"
        outString += self.buildScoreTable(leader_boards['earn'],amounts['earn'],'Earners')
        outString += "\n"
        outString += self.buildScoreTable(leader_boards['spend'],amounts['spend'],'Spenders')
        outString += "```"
        await ctx.send(outString)
        return

    def buildScoreTable(self, players: list[Player], amounts: list[int], toketype: str) -> str:
        max_name_length = max(len(str(player.name)) for player in players)
        max_amount_length = max(len(str(amount)) for amount in amounts)
        if max_amount_length < 4:
            max_amount_length = 4
        
        outString = f"-=Top Piter Death Token {toketype}=-\n"
        name_head = 'name'
        rank_head = 'rank'
        amnt_head = 'amount'

        outString += f"| {rank_head.ljust(6)} | {name_head.ljust(max_name_length +2)} | {amnt_head.ljust(max_amount_length +2)} |\n"
        outString += f"|{'-'*8}+{'-'*(4 + max_name_length)}+{'-'*(4+max_amount_length)}|\n"
        for i, player in enumerate(players):
            rank = str(i + 1)
            name = player.name
            amount = str(amounts[i])
            outString += f"| {rank.ljust(6)} | {name.ljust(max_name_length + 2)} | {amount.rjust(max_amount_length + 2)} |\n"

        return outString
