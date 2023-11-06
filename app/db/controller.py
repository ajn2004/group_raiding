from app.db.database import session_scope
from app.db.models import Player, Usage
from datetime import datetime


class DBController:

    def track_usage(self, ctx, command = '') -> None:
        with session_scope() as session:
            if not command:
                command = ctx.message.content
            if player := session.query(Player).filter(Player.discord_id == ctx.author.id).first():
                session.add(Usage(player_id = player.id,
                                  command = command,
                                  timestamp = datetime.utcnow()))
                session.commit()
                
    def pdt_trade(self, trade_object) -> str:
        
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
                        session.add(sender)
                        session.add(receiver)
                        session.commit()
                        return f"{sender.name} sent {trade_object['amount']} of PDT to {receiver.name}"
                    else:
                        return f"RIP bozo! You're too poor to send {trade_object['amount']} {sender.name}"
                else:
                    return "Invalid Receiver"
            else:
                return "Invalid Sender"

    def get_guild(self) -> dict:
        # Return an object of player discord ids
        guild = {}
        with session_scope() as session:
            players  = session.query(Player).all()
        for player in players:
            guild[player.name] = player.discord_id
            
        return guild
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
                return {'rip':'bozo'}
