from discord import player
from discord.ext import commands

class Presynapse(commands.Cog):
    # Administration automation 
    def __init__(self, bot , db_controller):
        self.bot = bot
        self.db_controller = db_controller
        self.admin = set([219443112567767041,189037705873588226,206240748692045836,245343112891858964])


    @commands.group(name='presyn', invoke_without_commands=True)
    async def presyn_group(self, ctx):
        # Entry point to all admin commands
        if player := self.db_controller.get_player(ctx.author.id):
            # Track any player who uses these commands
            self.db_controller.track_usage(ctx)
        else:
            # Send a kind message
            await ctx.send(f"```/gkick {player.name}```")
            return

    @presyn_group.command(name='swap')
    async def swap(self, ctx):
        inCommand = ctx.message.content.split(' ')
        if len(inCommand) != 3:
            await ctx.send("swap takes a single command e.g. !presyn swap 1")
            return
        if int(inCommand[2]) < 0 or int(inCommand[2]) > 5:
            await ctx.send("You must select 0-5 where 0 = General Raiding and 5 = AFK")
            return

        admins = set([219443112567767041,189037705873588226,206240748692045836,245343112891858964])

        # Determine which group to send to
        channels = {
            '0' : 386962860821053450,
            '1' : 848615257706332190,
            '2' : 873716323736231966, # officer channel
            '3' : 848615282419040266,
            '4' : 849869524039368724,
            '5' : 690801950987649076,
            }
        channel = self.bot.get_channel(channels[inCommand[2]])
        # get a list of players
        guild = self.db_controller.get_guild()

        # Cycle through players and if they are online move them to a new channel
        for player in guild.keys():
            member = ctx.guild.get_member(guild[player])
            if member and member.voice:
                # Swap to officer should move officers only
                if inCommand[2] != '2':
                    await member.move_to(channel)
                else:
                    if guild[player] in admins:
                        await member.move_to(channel)
        await ctx.message.delete()

