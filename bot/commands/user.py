from bot import bot
from app import app
from app.models import *
from discord import Interaction, message
from functools import wraps

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

def getPlayer(discord_id):
    with app.app_context():
        return Player.query.filter_by(discord_id = discord_id).first()
        
        
