# from app.config import DISCORD_BOT_TOKEN
from app.config import DISCORD_BOT_TOKEN
from app.discord_bot.bot import bot

if __name__ == '__main__':
    # Run the bot with your token
    bot.run(DISCORD_BOT_TOKEN)
