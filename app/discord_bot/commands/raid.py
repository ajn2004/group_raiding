from discord import player
from discord.ext import commands
import json

class Raid(commands.Cog):
    # Administration automation 
    def __init__(self, bot , db_controller):
        self.bot = bot
        self.db_controller = db_controller
        self.file_name = 'data/loot-data.json'
        self.classList = set([
            'warrior', 'paladin', 'rogue',
            'druid', 'death knight', 'shaman',
            'warlock', 'mage', 'priest', 'hunter'    
            ])

    @commands.group(name='raid')
    async def raid_group(self, ctx):
        if player:= self.db_controller.get_player(ctx.author.id):
            self.db_controller.track_usage(ctx)
        else:
            await ctx.send("Who are you people?")
            return

    @raid_group.command(name='addAlt')
    async def addAlt(self, ctx):
        inCommand = ctx.message.content.split('!raid addAlt')
        if inCommand[1] ==' ' or inCommand[1] == '' or inCommand[1] == ' ?':
            await ctx.send(f"To add an alt use !raid addAlt 'Altname' 'Altclass'")
            await ctx.message.delete()
            return
        else:
            # input handling
            altInfo = inCommand[1][1:].split(' ')

            # Check input command looks right
            if len(altInfo) == 1:
                await ctx.send(f"To add an alt use !raid addAlt 'Altname' 'Altclass'")
                await ctx.message.delete()
                return

            # if class has a space we'll need to concat indexes 1 and 2
            if len(altInfo) == 3:
                altInfo[1] += ' ' + altInfo[2]
            
            # standardize input for database
            name = altInfo[0].lower()
            className = altInfo[1].lower()
        
            # check valid class input
            if className not in self.classList:
                await ctx.send(f"Invalid Class: Warrior Hunter Paladin Rogue Druid Death Knight Mage Priest or Warlock")
                await ctx.message.delete()
                return

            if player := self.db_controller.get_player(ctx.author.id):
                alt_object = { # Construct alt object
                    'class' : className,
                    'player_id' : player['id'],
                    'name' : name,
                    }
                await ctx.send(self.db_controller.add_alt(alt_object))
                await ctx.message.delete()
                return
                
    @raid_group.command(name='noNext')
    async def noNext(self,ctx):
        # Return a table of players who have low loot prios
        inCommand = ctx.message.content.split('!raid noNext')
        n = 5 # default this
        if inCommand[1] ==' ?':
            await ctx.send('use `!raid noNext n` to see the n lowest loot prio players currently')
        else:
            try:
                n = int(inCommand[1])
            except:
                n = 5
        with open(self.file_name, 'r') as json_file:
            data = json.load(json_file)
        # next_prios should be keyed to player
        next_prios = {}
        for player in data.keys():
            if data[player]['raid_group_name'] == 'Presynaptic 25':
                # player object should have n: number of next drops and a list of what drops
                next_prios[player] = {'n':0,'prios':[]}
                # Loop over prios
                prios = data[player]['prios']
                for prio in prios:
                    if prio['pivot']['is_received'] == 0 : # the item is only prio'd
                        if prio['pivot']['order'] == 1:
                            next_prios[player]['n']  += 1
                        next_prios[player]['prios'].append([prio['name'],prio['pivot']['order']])
        sorted_players = sorted(next_prios.items(), key=lambda x: x[1]['n'])
        top_n_players = sorted_players[:n]
        outString = "```\n"
        outString += f"| {'Player Name'.ljust(11)} | Nexts |\n"
        outString += f"|{'-'*13}+{'-'*7}|\n"
        for player, details in top_n_players:
            outString += f"| {str(player).ljust(11)} | {str(details['n']).rjust(5)} |\n"
        outString += '```'
        await ctx.send(outString)
        await ctx.message.delete()
                
        
    @raid_group.command(name='shards')
    async def shards(self, ctx):
        inCommand = ctx.message.content.split('!raid shards')
        if inCommand[1] ==' ' or inCommand[1] == '' or inCommand[1] == ' ?':
            await ctx.send(f"To view shards use !raid shards 'Name'")
            await ctx.message.delete()
            return
        with open(self.file_name, 'r') as json_file:
            data = json.load(json_file)
            try:
                toon = data[inCommand[1][1:].lower()]['received']
            except:
                await ctx.send("To view shards use !raid shards 'Name'")
                return
        count = 0
        for item in toon:
            if item['name'] == 'Shadowfrost Shard':
                count += 1
        await ctx.send(f"{inCommand[1]} has received {count} Shadowfrost Shards out of 50")
        await ctx.message.delete()
        return
