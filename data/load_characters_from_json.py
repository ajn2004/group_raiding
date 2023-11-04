import json
from app import app
from app.models import *

with open('data/character-json.json', 'r') as json_file:
    data = json.load(json_file)

toons = []
missing_toons ={
    'derangex':['derangex','druid',True],
    'hurfnarfaful' : ['gekker','hunter', True],
    'issild' : ['romsca', 'priest', False],
    'morogat' : ['moro', 'warrior', True],
    'mororogue' : ['moro', 'rogue', False],
    'thumpystump' : ['thumpy', 'shaman', True],
    }
with app.app_context():
    for datum in data:
        character = Character.query.filter_by(name = datum['slug']).first()
        if character:
            character.class_name = character.class_name.lower()
            character.mainAlt = True
            db.session.add(character)
        if datum['slug'] in missing_toons.keys():
            player = Player.query.filter_by(name = missing_toons[datum['slug']][0]).first()
            if player:
                # add character to be associated w/ player
                toons.append(Character(name=datum['slug'],
                                       class_name= missing_toons[datum['slug']][1],
                                       mainAlt= missing_toons[datum['slug']][2],
                                       player_id=player.id))
            
                print(datum['slug'] + ' was added as a ' + datum['class'].lower())
            else:
                print(datum['slug'] + ' was not found as a ' + datum['class'])
    db.session.bulk_save_objects(toons)
    db.session.commit()

