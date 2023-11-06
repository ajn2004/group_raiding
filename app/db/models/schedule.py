from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship

from .base import Base


class Schedule(Base):
    __tablename__ = 'schedule'

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    available = Column(Integer)  # encoding days available as a 7-bit binary
    player = relationship('Player', backref='schedules')

    def __init__(self, player_id, available=[0, 0, 0, 0, 0, 0, 0]) -> None:
        if len(available) == 7:
            self.player_id = player_id
            self.available = self.days2bin(available)

    def __repr__(self) -> str:
        # player = Player.query.filter_by(id = self.player_id).first()
        outString = self.weekString()
        return f'<player {self.player.name}\n| Sun | Mon | Tue | Wed | Thu | Fri | Sat |\n|-----+-----+-----+-----+-----+-----+-----|\n{outString}>'

    def printWeek(self) -> None:
        print('| Sun | Mon | Tue | Wed | Thu | Fri | Sat |')
        print('|-----+-----+-----+-----+-----+-----+-----|')
        weekstr = self.weekString()
        print(weekstr)

    def weekString(self) -> str:
        days = self.bin2days(self.available)
        weekstr = '|'
        for day in days:
            if day:
                weekstr += ' yes |'
            else:
                weekstr += ' no  |'
        return weekstr

    def getWeek(self) -> list:
        return self.bin2days(self.available)


    def days2bin(days=[0, 0, 0, 0, 0, 0, 0]):
        # days is a binary list so we can create an integer value to story a person's availability
        # the order will be sunday will be the 0 index and saturday will be the 6 index
        number = 0

        for i in range(len(days)):
            number += days[i] * 2 ** i
        return number


    def bin2days(binNumber) -> list:
        days = []

        for i in range(7):
            # indexing through days where sun = 0 sat = 6
            day_bit = binNumber & 1
            days.append(day_bit)
            binNumber >>= 1
        days.reverse()
        return days