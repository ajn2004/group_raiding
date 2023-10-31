from bot import bot
import os
if __name__ == '__main__':
    # Run the bot with your token
    bot.run(os.getenv("DISCORD_BOT_TOKEN"))
