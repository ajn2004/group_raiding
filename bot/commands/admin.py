from bot import bot
from app import app
from app.models import *
from discord import Interaction, message

# Admin Commands
admins = set([219443112567767041,189037705873588226,206240748692045836,245343112891858964])
# @bot.group(invoke_without_command=True)

def trackUsage(ctx):
    # track usage
    with app.app_context():
        player = Player.query.filter_by(discord_id = ctx.author.id).first()
        if player:
            db.session.add(Usage(player_id=player.id,
                                 command=ctx.message.content,
                                 timestamp=datetime.utcnow()))
            db.session.commit()
    return

@bot.group()
async def presyn(ctx):
    trackUsage(ctx)
    #Admin functions authorize usage
    if ctx.author.id not in admins:
        await ctx.send("You're not allowed to do that.")
        await ctx.message.delete()
        return

@presyn.command()
async def swap(ctx):
    inCommand = ctx.message.content.split(' ')
    if len(inCommand) != 3:
        await ctx.send("swap takes a single command e.g. !presyn swap 1")
        return
    if int(inCommand[2]) < 0 or int(inCommand[2]) > 5:
        await ctx.send("You must select 0-5 where 0 = General Raiding and 5 = AFK")
        return

    # Determine which group to send to
    channels = {
        '0' : 386962860821053450,
        '1' : 848615257706332190,
        '2' : 873716323736231966,
        '3' : 848615282419040266,
        '4' : 849869524039368724,
        '5' : 690801950987649076,
        }
    channel = bot.get_channel(channels[inCommand[2]])
    # swap users to voice group
    with app.app_context():
        players = Player.query.all()
        # print(players)

    # Cycle through players and if they are online move them to a new channel
    for player in players:
        if player:
            member = ctx.guild.get_member(player.discord_id)
            print(member)
            if member and member.voice:
                await member.move_to(channel)
    await ctx.message.delete()
    
@presyn.command()
async def officer(ctx):
    players = []
    channel = bot.get_channel(873716323736231966)
    with app.app_context():
        for admin_id in admins:
            player = Player.query.filter_by(discord_id = admin_id).first()
            if player:
                member = ctx.guild.get_member(player.discord_id)
                if member and member.voice:
                    await member.move_to(channel)
    await ctx.message.delete()
