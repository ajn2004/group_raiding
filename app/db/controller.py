from app.db.database import session_scope
from app.db.models import Player


class DBController:

    def trade(self, trade_object) -> str:
        with session_scope() as session:
            players = session.query(Player)
            # check sender
            if sender := players.filter(Player.discord_id == trade_object['sender']).first():
                if receiver := players.filter(Player.discord_id == trade_object['receiver']).first():
                    if trade_object['amount'] <= sender.piter_death_tokens:
                        sender.piter_death_tokens -= trade_object['amount']
                        receiver.piter_death_tokens += trade_object['amount']
                        sender.tokens_spent += trade_object['amount']
                        receiver.tokens_received += trade_object['amount']
                        return f"{sender.name} sent {trade_object['amount']} of PDT to {receiver.name}"
                else:
                    return "Invalid Receiver"
            else:
                return "Invalid Sender"

    
    def get_player(self, player_id) -> dict:
        with session_scope() as session:
            if player := session.query(Player).filter(Player.discord_id == player_id).first():
                return {
                    'id': player.id,
                    'name': player.name,
                    'piter_death_tokens': player.piter_death_tokens,
                    'spent': player.tokens_spent,
                    'received' : player.tokens_received
                }
            else:
                return {}
