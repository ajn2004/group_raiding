from app.casino.books.base_book import BaseBook


class Deadpool(BaseBook):

    def __init__(self):
        super().__init__()
        self.book_type = "deadpool"

    def add_bet(self, **kwargs):
        pass

    def resolve_book(self, **kwargs):
        pass
