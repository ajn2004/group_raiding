from app.casino.books.base_book import BaseBook


class WipePrediction(BaseBook):

    def __init__(self):
        super().__init__()
        self.book_type = "wipe_prediction"

    def add_bet(self, **kwargs):
        pass

    def resolve_book(self, **kwargs):
        pass
