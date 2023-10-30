from enum import unique
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import backref

db = SQLAlchemy()

class Player(db.Model):
    __tablename__ = 'players'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique = True, nullable=False)
    characters = db.relationship('Character', backref='player', lazy=True)

    def __init__(self, name):
        name.lower()
        self.name = name
        
    def __repr__(self):
        return f'<Player {self.name}>'

class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    available = db.Column(db.Integer) # encoding days available as a 7-bit binary
    player = db.relationship('Player', backref='schedules')
    
    def __init__(self, player_id, available=[0,0,0,0,0,0,0]) -> None:
        if len(available) == 7:
            self.player_id = player_id
            self.available = days2bin(available)


    def __repr__(self) -> str:
        # player = Player.query.filter_by(id = self.player_id).first()
        return f'<Schedule {self.available} player {self.player.name}>'

    def printWeek(self) -> None:
        print('| Sun | Mon | Tue | Wed | Thu | Fri | Sat |')
        print('|-----+-----+-----+-----+-----+-----+-----|')
        days = bin2days(self.available)
        weekstr = '|'
        for day in days:
            if day:
              weekstr += ' yes |'
            else:
              weekstr += ' no  |'
        print(weekstr)
        print(days)
            

def days2bin(days=[0,0,0,0,0,0,0]):
    # days is a binary list so we can create an integer value to story a person's availability
    # the order will be sunday will be the 0 index and saturday will be the 6 index
    number = 0
    
    for i in range(len(days)):
        number += days[i]*2**i
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

class Character(db.Model):
    __tablename__ = 'characters'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    class_name = db.Column(db.String(50), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    specializations = db.relationship('Specialization', backref='character', lazy=True)

    def __init__(self, name, class_name, player_id):
        name.lower()
        self.name = name
        class_name.lower()
        self.class_name = class_name
        self.player_id = player_id
    
    def __repr__(self):
        return f'<Character {self.name}>'

class Specialization(db.Model):
    __tablename__ = 'specializations'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False) # 1 tank 2 melee 3 ranged 4 heals
    gearscore = db.Column(db.Integer, nullable=False)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id'), nullable=False)
    buffs = db.relationship('Buff', backref='specialization', lazy='dynamic')

    def __init__(self, name, role_id, gearscore, character_id):
        name.lower()
        self.name = name
        self.role_id = role_id
        self.gearscore = gearscore
        self.character_id = character_id
        
    def __repr__(self):
        role = Role.query.get(self.role_id)
        return f'<Specialization {self.name}, Role {role.name}>'

class Role(db.Model):
    __tablename__ = 'roles'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    specializations = db.relationship('Specialization', backref='role', lazy=True)
    def __init__(self, name):
        name.lower()
        self.name = name
        
    def __repr__(self):
        return f'<Role {self.name}>'

class Buff(db.Model):
    __tablename__ = 'buffs'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    raidscore = db.Column(db.Integer, nullable=True)
    specialization_id = db.Column(db.Integer, db.ForeignKey('specializations.id'), nullable=False)

    def __init__(self, name, raidscore, spec_id):
        name.lower()
        self.name = name
        self.raidscore = raidscore
        self.specialization_id = spec_id
        
    def __repr__(self):
        return f'<Buff {self.name}>'

# Setup for Flask application, typically in a separate file like app.py
# from flask import Flask
# from models import db

# app = Flask(__name__)
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///your_database.db'
# db.init_app(app)

# with app.app_context():
#     db.create_all()  # Creates all tables
