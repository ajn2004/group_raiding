import time

from abc import ABC, abstractmethod
from datetime import datetime


class BaseBook(ABC):

    def __init__(self):
        self.book_id = f"{self.__class__.__name__}-{time.mktime(datetime.now().timetuple())}"
        self.bets = []

    @abstractmethod
    def add_bet(self, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def resolve_book(self, **kwargs):
        raise NotImplementedError

