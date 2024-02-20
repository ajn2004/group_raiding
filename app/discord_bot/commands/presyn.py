from datetime import datetime
import time
from os import name
from discord import asyncio, message, player
from discord import Bot
from discord.ext import commands
from app.db.controller import DBController
from app.discord_bot.commands.sod import RESET_INTERVAL
from .memes import FRI, MON, SAT, SUN, THU, TUE, WED, Memes, PDT, channel_info, handleSchedulePoll, known_sod_reset, lock_prompt, next_weekday

class Presynapse(commands.Cog):
    # Administration automation 
    def __init__(self, bot: Bot, db_controller: DBController) -> None:
        self.bot = bot
        self.db_controller = db_controller
        self.admin = set([219443112567767041, 189037705873588226, 206240748692045836, 245343112891858964])
            
    @commands.group(name='presyn', invoke_without_commands=True)
    async def presyn_group(self, ctx: commands.Context) -> None:
        # Entry point to all admin commands
        if player := self.db_controller.get_player(ctx.author.id):
            # Track any player who uses these commands
            self.db_controller.track_usage(ctx)
            if ctx.author.id in self.admin:
                pass
            else:
                await ctx.send(f"```/gkick {player['name']}```")
                return
        else:
            # Send a kind message
            await ctx.channel.send(file = Memes().getMeme('patrick'))
            return

    @presyn_group.command(name='buy')
    async def buy(self, ctx: commands.Context) -> None:
        inCommand = ctx.message.content.split(' ')
        if len(inCommand) != 3:
            await ctx.send("buy takes a single command e.g. !presyn buy 100")
            return
        try:
            self.db_controller.add_all(int(inCommand[-1]))
            await ctx.send(PDT*3 + " BUY"*3 + PDT*3 + f" everyone just got {inCommand[-1]} PDT!")
            await ctx.message.delete()
            return
        except:
            return
        
    @presyn_group.command(name='schedule')
    async def schedule(self, ctx: commands.Context) -> None:
        # spawn a schedule prompt so we can read off the data
        # prompt = "@everyone what nights would you prefer to raid?"
        prompt = "@everyone what nights would you prefer to raid this week?"
        prompt += lock_prompt[next_weekday(datetime.now(), 0).day % RESET_INTERVAL]
        prompt += lock_prompt[3]

        # Send to correct channel (raiding)
        channel_id = channel_info['raiding']

        # sending logic
        if channel:=self.bot.get_channel(channel_id):
            message = await channel.send(prompt)
            pass
        else:
            return

        # Emoji logic
        emojis = [MON, TUE, WED, THU, FRI, SAT, SUN]
        for emoji in emojis:
            await message.add_reaction(emoji=emoji)

        # wait for some time in seconds
        days = 2
        await asyncio.sleep(round(3600*24*days))
        # await asyncio.sleep(30)

        # prepare to count reactions
        message = await channel.fetch_message(message.id)
        reaction_counts = {}
        for reaction in message.reactions:
            if reaction.emoji in emojis:  # Check if the reaction is one of the emojis we're interested in
                reaction_counts[str(reaction.emoji)] = reaction.count - 1  # Subtract 1 to exclude the bot's own reaction
        
        # Compile and send the summary message
        summary_message = "Raid night preferences:\n"
        results = []
        for emoji, count in reaction_counts.items():
            summary_message += f"{emoji}: {count} votes\n"
            results.append(count)
        await channel.send(summary_message)
        raid_strings = handleSchedulePoll(results=results,raids=2)

        # Deliver strings to officer
        if channel := self.bot.get_channel(channel_info['officer']):
            for raid_string in raid_strings:
                await channel.send(raid_string)
        return None
    
    @presyn_group.command(name='swap')
    async def swap(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
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
        if channel:=self.bot.get_channel(channels[inCommand[2]]):
            pass
        else:
            return
        # get a list of players
        guild = self.db_controller.get_guild()

        # Cycle through players and if they are online move them to a new channel
        for player in guild.keys():
            if member := ctx.guild.get_member(guild[player]):
                if member.voice:
                    # Swap to officer should move officers only
                    if inCommand[2] != '2':
                        await member.move_to(channel)
                    else:
                        if guild[player] in admins:
                            await member.move_to(channel)
        await ctx.message.delete()


