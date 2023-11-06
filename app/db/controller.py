from app.db.database import session_scope
from app.db.models import Player


class DBController:

    def get_player(self, player_id) -> dict:
        with session_scope() as session:
            if player := session.query(Player).filter(Player.discord_id == player_id).first():
                return {
                    'id': player.id,
                    'name': player.name,
                    'piter_death_tokens': player.piter_death_tokens
                }
