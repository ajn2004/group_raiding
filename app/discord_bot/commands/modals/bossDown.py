from discord.ui import Modal, InputText
from discord import InputTextStyle, Interaction
from app.db.controller import DBController

class pdtBettingModal(Modal):
    def __init__(self, *args, boolean_value, discord_id, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.boolean_value = boolean_value
        self.player = DBController().get_player(discord_id)
        self.add_item(InputText(label="Enter an Integer", style=InputTextStyle.short))

    async def callback(self, interaction: Interaction) -> None:
        # At this point we want to let the user make a bet
        try:
            if self.children[0].value:
                if int(self.children[0].value)>=0:
                    integer_value = int(self.children[0].value)
                    pass
            else:
                integer_value = 0 # valueError should prevent this case from happening
            # check the user has enough pdt
            # Do something with the boolean value and integer value
            if self.player:
                if self.player['piter_death_tokens'] >= integer_value:
                    result = {True:'Kill', False: 'Wipe on'}
                    await interaction.response.send_message(f"You've bet {integer_value} that we will {result[self.boolean_value]} the boss!", ephemeral=True)
                    pass
                else:
                    await interaction.response.send_message("RIP Bozo, you're too poor for that number", ephemeral=True)
            # await interaction.response.send_message(f"You chose {self.boolean_value} and entered the integer {integer_value}.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Please enter a valid integer.", ephemeral=True)
