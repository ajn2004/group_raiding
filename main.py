from app.discord_bot.bot import bot
from app.config import DISCORD_BOT_TOKEN

if __name__ == '__main__':
    # Run the bot with your token
    bot.run(DISCORD_BOT_TOKEN)
    # print(DISCORD_BOT_TOKEN)
