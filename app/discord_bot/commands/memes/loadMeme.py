'''This file should be the central loading point for all memes'''
# from datetime import datetime
import datetime as dt
from sre_constants import SUBPATTERN
import discord

known_sod_reset = dt.datetime(2023, 12, 21)

PDT = '<:pdt:1009279728366137425>'
MON = '🇲'
TUE = '🇹'
SUN = '🇸'
SAT = '🛰'
WED = '🇼'
THU = '🇷'
FRI = '🇫'

# Handle Raid Strings here
raid_string = {'BFD': ['BFD 10', 'Season of Discovery Blackfathom Deeps', 37],
               'GNM': ['GNM 10', 'Season of Disvovery Gnomeregan', 37]}

channel_info = {'monday': 1093701473340227674,
               'tuesday': 1009788705902432276,
               'wednesday':1009788800957939782,
               'thursday': 1023239799315902594,
               'friday': 1121968991297089687,
               'saturday': 1023239844173983827,
               'sunday': 1121969064647065720,
               'raiding': 851646675746947073,
               'officer': 849871979326210069,
                'bots': 859098239282577418}

days_of_week = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']

lock_prompt = [f"\n|-------lockout -------|------lockout -------|------",
               f"\n--------|-------lockout-------|------lockout ------|",
               f"\n----lockout ---|-------lockout -------|---lockout---",
               f"\n|  Mon   |  Tue    |  Wed   |  Thu   |   Fri     |  Sat   |  Sun  |\n"]

def create_raid_string(date: dt.date = dt.datetime.today(),
                       template: int = 37,
                       title: str = 'Gnomeregan 10 man',
                       description: str = '10 man Gnomeregan guild run',
                       channel: str = days_of_week[dt.datetime.today().weekday()]) -> str:
    return f"/quickcreate [template: {template}] [title: {title}] [description: {description}] [date: {date.strftime('%d-%m-%Y')}] [time: 19:00] [channel: {channel}]"
    
def handleSchedulePoll(results: list[int] = [0, 1, 0, 0, 0, 0, 0], raids: int = 2) -> list[str]:
    # sort the incoming list of results
    # we assum [m,t,w,th,f,sa,su] ordering
    sorted_index = sorted(range(len(results)), key=lambda k: results[k])
    raid_strings = []
    for i in range(raids):
        j = len(results) - i - 1
        date = next_weekday(dt.datetime.now(), sorted_index[j])
        raid_strings.append(create_raid_string(date, channel=days_of_week[date.weekday()]))
    return raid_strings

def next_weekday(d: dt.date = dt.datetime.now(), weekday: int = dt.datetime.now().weekday()) -> dt.date:
    # monday is default
    days_ahead = weekday - d.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return d + dt.timedelta(days_ahead)

class Memes:
    memeFile = {
    'patrick':'app/memes/patrick.gif',
    'obama':'app/memes/obama_meme.jpg'
    }
    
    def getMeme(self, meme: str) -> discord.File:
        with open(self.memeFile[meme], 'rb') as f:
            return discord.File(f)
