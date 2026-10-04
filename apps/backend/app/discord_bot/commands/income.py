from discord import Bot, player
import discord
from discord.ext import commands
from app.db.controller import DBController
from .memes.loadMeme import Memes, PDT
from .modals import pdtBettingModal
import random
from datetime import datetime
from functools import partial

class Income(commands.Cog):
    # define ways to get PDT through discord interactions
    def __init__(self, bot: Bot, db_controller: DBController) -> None:
        self.bot = bot
        self.db_controller = db_controller

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        add_object = {'player':message.author.id, 'amount' : random.randint(5,15)}
        if self.db_controller.add_pdt(add_object=add_object):
            self.db_controller.track_usage(message, command = f'income of {add_object["amount"]} for message')
        if random.randint(0,100) < 9:
            try:
                await message.add_reaction(emoji=PDT)
            except Exception as e:
                print("Unable to react...")
        return

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.member:
            if payload.member.id == 1168641939873202196:
                return
            add_object = {'player':payload.member.id, 'amount' : random.randint(5,15)}
            if str(payload.emoji) == PDT:
                add_object['amount'] *= random.randint(2,4)
                print('reaction',add_object)
            if self.db_controller.add_pdt(add_object=add_object):
                self.db_controller.track_usage('',user=payload.member.id,  command = f'income of {add_object["amount"]} pdt for reaction') 
