'''This file should be the central loading point for all memes'''
import discord

PDT = '<:pdt:1009279728366137425>'
class Memes:
    memeFile = {
    'patrick':'app/memes/patrick.gif',
    'obama':'app/memes/obama_meme.jpg'
    }
    
    def getMeme(self, meme: str) -> discord.File:
        with open(self.memeFile[meme], 'rb') as f:
            return discord.File(f)
