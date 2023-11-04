from bot import bot
from app import app
from app.models import *
import json
from discord import Interaction, message
from functools import wraps
from sqlalchemy import desc

# A command that responds with a personalized message
@bot.command(name='hello')
async def hello(ctx):
    await ctx.send(f'Hello, {ctx.author.name}!')

# @bot.group(invoke_without_command=True)

# Piter Death Token
@bot.group()
async def pdt(ctx):
    pass

# @bot.add_command(name="pdt", description="Check your PiterDeathToken Balance")
@pdt.command()
async def check(ctx):
    with app.app_context():
        player = Player.query.filter_by(discord_id = ctx.author.id).first()
    if player:
        name = player.name
        await ctx.send(f"{name} has a balance of {player.piter_death_tokens} PiterDeathTokens.")
    else:
        await ctx.send(f"Who are you people?")
    await ctx.message.delete()

@pdt.command()
async def top(ctx):
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
    with app.app_context():
        # get top n players in tokens held, tokens spent, and tokens received
        top_holders = Player.query.order_by(desc(Player.piter_death_tokens)).limit(n).all()
        top_spenders = Player.query.order_by(desc(Player.tokens_spent)).limit(n).all()
        top_earners = Player.query.order_by(desc(Player.tokens_recieved)).limit(n).all()
    outString = "```\n"

    # Print top holders
    amounts = []
    for player in top_holders:
        amounts.append(player.piter_death_tokens)
    outString += buildScoreTable(top_holders, amounts, "Holders")

    outString += "\n"
    # print top spenders
    amounts = []
    for spender in top_spenders:
        amounts.append(spender.tokens_spent)
    outString += buildScoreTable(top_spenders, amounts, "Spenders")

    outString += "\n"
    # print top earners
    amounts = []
    for player in top_earners:
        amounts.append(player.tokens_recieved)
    outString += buildScoreTable(top_earners, amounts, "Earners")

    outString += "\n"
    # end string and send
    outString += "```"
    await ctx.send(outString)
        
def buildScoreTable(players, amounts, toketype):
    # Print top table
    outString = f"-=Top Piter Death Token {toketype} =-\n"
    outString += "| Rank | Name        | Amount |\n"
    outString += "|------|-------------|--------|\n"
    for i in range(len(players)):
        outString += f"| {str(i + 1).ljust(4)} | {players[i].name.ljust(11)} | {str(amounts[i]).rjust(6)} |\n"
    return outString

@pdt.command()
async def trade(ctx):
    inCommand = ctx.message.content.split('!pdt trade')
    if inCommand[1] ==' ' or inCommand[1] == '' or inCommand[1] == ' ?':
        await ctx.send(f"To trade PDT use !pdt Player Amount")    
        await ctx.message.delete()
        return
    print(inCommand)
    toPlayer, amount = inCommand[1][1:].split(' ')
    toPlayerId = int(toPlayer[2:-1])
    amount = abs(int(amount))
    print(toPlayerId)
    print(amount)
    if not amount:
        await ctx.send(f"To trade PDT use !pdt Player Amount")    
        await ctx.message.delete()
        return
    else:
        with app.app_context():
            try:
                player = Player.query.filter_by(discord_id = ctx.author.id).first()
                # validate user
                if player:
                    sendPlayer = Player.query.filter_by(discord_id = toPlayerId).first()
                    if sendPlayer:
                        if player.id == sendPlayer.id:
                            await ctx.send(f"{player.name} that's just passing the same fish back and forth")
                            return
                        if player.piter_death_tokens >= amount:
                            player.piter_death_tokens -= amount
                            sendPlayer.piter_death_tokens += amount
                            sendPlayer.tokens_earned += amount
                            player.tokens_spent += amount
                            db.session.add(player)
                            db.session.add(sendPlayer)
                            db.session.commit()
                            await ctx.send(f"{player.name} just sent {amount} PDT to {sendPlayer.name}")
                        else:
                            await ctx.send(f"RIP bozo, you're too poor to send {amount}.")
                    else:
                        await ctx.send(f"Couldn't find that player in our database")
            except Exception as e:
                db.session.rollback()
                await ctx.send("An error occurred while processing the transaction.")
                print(f"An error occurred: {e}")
        await ctx.message.delete()
        return
    
# Code to allow players to interact with our database
@bot.group()
async def raid(ctx):
    pass

classList = set([
    'warrior', 'paladin', 'rogue',
    'druid', 'death knight', 'shaman',
    'warlock', 'mage', 'priest', 'hunter'    
    ])
# allow players to add an alt to the database
@raid.command()
async def addAlt(ctx):
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
        if className not in classList:
            await ctx.send(f"Invalid Class: Warrior Hunter Paladin Rogue Druid Death Knight Mage Priest or Warlock")
            await ctx.message.delete()
            return

        # Add character to Player's database
        player = getPlayer(ctx.author.id)
        if player:
            with app.app_context():
                checkCharacter = Character.query.filter_by(name=name).first()
                if checkCharacter:
                    await ctx.send(f"The character {checkCharacter.name} already exists")
                    await ctx.message.delete()
                    return
                alts = Character.query.filter_by(player_id = player.id).first()
                mainAlt = True
                if alts:
                    mainAlt = False
                    
                character = Character(name = name, class_name=className, player_id=player.id, mainAlt=mainAlt)
                db.session.add(character)
                db.session.commit()
                await ctx.send(f"Added {character.name} to the database")
                await ctx.message.delete()
                return

# allow players to edit alt in the database
@raid.command()
async def editAlt(ctx):
    pass

# allow players to add their schedule
@raid.command()
async def addSched(ctx):
    pass

# allow players to edit their schedule
@raid.command()
async def editSched(ctx):
    pass

@raid.command()
async def shards(ctx):
    inCommand = ctx.message.content.split('!raid shards')
    if inCommand[1] ==' ' or inCommand[1] == '' or inCommand[1] == ' ?':
        await ctx.send(f"To view shards use !raid shards 'Name'")
        await ctx.message.delete()
        return
    with open('data/loot-data.json', 'r') as json_file:
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

def getPlayer(discord_id):
    with app.app_context():
        return Player.query.filter_by(discord_id = discord_id).first()
        
        
