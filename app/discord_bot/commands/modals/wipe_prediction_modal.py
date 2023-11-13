from discord.ui import Modal, InputText
from discord import InputTextStyle, Interaction
from app.db.controller import DBController


class WipePredictionModal(Modal):
    def __init__(self, *args, boolean_value, discord_id, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.boolean_value = boolean_value
        self.player = DBController().get_player(discord_id)
        self.add_item(InputText(label="Enter an Integer", style=InputTextStyle.short))
