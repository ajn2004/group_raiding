'''This file should be the central loading point for all memes'''
from sre_constants import SUBPATTERN
import discord

PDT = '<:pdt:1009279728366137425>'
MON = '🇲'
TUE = '🇹'
SUN = '🇸'
SAT = '🛰'
WED = '🇼'
THU = '🇷'
FRI = '🇫'
class Memes:
    memeFile = {
    'patrick':'app/memes/patrick.gif',
    'obama':'app/memes/obama_meme.jpg'
    }
    
    def getMeme(self, meme: str) -> discord.File:
        with open(self.memeFile[meme], 'rb') as f:
            return discord.File(f)
