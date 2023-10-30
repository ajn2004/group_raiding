from .models import *
from app import db

def load_guild():
    load_roles()
    load_balton()
    load_deego()
    db.session.commit()

def load_roles():
    # build out raid roles
    roles = []
    roles.append(Role(name = "tank"))
    roles.append(Role(name="melee"))
    roles.append(Role(name="ranged"))
    roles.append(Role(name="heals"))
    db.session.bulk_save_objects(roles)
    
def load_deego():
    newDeego = Player(name = "deego")
    db.session.add(newDeego)
    DEEGO =  Player.query.filter_by(name = "deego").first()
    tank = Role.query.filter_by(name = "tank").first()
    heal = Role.query.filter_by(name = "heals").first()
    melee = Role.query.filter_by(name = "melee").first()
    ranged = Role.query.filter_by(name = "ranged").first()
    # Add Deego Characters
    toons = []
    toons.append(Character(name = "cities", class_name = "paladin", player_id = DEEGO.id))
    toons.append(Character(name = "wynt", class_name = "mage", player_id = DEEGO.id))
    toons.append(Character(name = "trumble", class_name = "hunter", player_id = DEEGO.id))
    toons.append(Character(name = "deego", class_name = "shaman", player_id = DEEGO.id))
    toons.append(Character(name = "blackthorn", class_name = "death knight", player_id = DEEGO.id))
    toons.append(Character(name = "steamedhams", class_name = "druid", player_id = DEEGO.id))
    toons.append(Character(name = "saynotozugs", class_name = "priest", player_id = DEEGO.id))

    db.session.bulk_save_objects(toons)

    # Character Specializations
    specs = {
        "cities":{"holy":[heal.id, 5126],"retribution": [melee.id, 5004]},
        "wynt":{"fire":[ranged.id, 5865]},
        "trumble":{"survival":[ranged.id, 5126]},
        "blackthorn":{"unholy":[melee.id, 3454]},
        "steamedhams":{"balance":[ranged.id, 5434], "restoration":[heal.id, 5343]},
        "saynotozugs":{"shadow":[ranged.id, 5432], "discipline":[heal.id,4895]}
        }
    specializ = []
    for name in specs.keys():

        toon = Character.query.filter_by(name = name).first()
        print(toon)
        for spec in specs[name].keys():
            specializ.append(Specialization(name = spec, role_id=specs[name][spec][0], gearscore=specs[name][spec][1], character_id=toon.id))
    db.session.bulk_save_objects(specializ)
    
def load_balton():
    # Seed info with Players
    newBalton = Player(name = "balton")
    db.session.add(newBalton)
    BALTON = Player.query.filter_by(name = "balton").first()
    tank = Role.query.filter_by(name = "tank").first()
    heal = Role.query.filter_by(name = "heals").first()
    melee = Role.query.filter_by(name = "melee").first()
    ranged = Role.query.filter_by(name = "ranged").first()
    
    # Add Balton Characters
    toons = []
    toons.append(Character(name = "balton", class_name = "warrior", player_id = BALTON.id))
    toons.append(Character(name = "ohval", class_name = "paladin", player_id = BALTON.id))
    toons.append(Character(name = "bouton", class_name = "mage", player_id = BALTON.id))
    toons.append(Character(name = "huntondis", class_name = "hunter", player_id = BALTON.id))
    toons.append(Character(name = "quhzx", class_name = "shaman", player_id = BALTON.id))
    toons.append(Character(name = "milarepa", class_name = "death knight", player_id = BALTON.id))
    toons.append(Character(name = "deathtoken", class_name = "rogue", player_id = BALTON.id))
    toons.append(Character(name = "rengekyo", class_name = "priest", player_id = BALTON.id))

    db.session.bulk_save_objects(toons)

    # character Specializations
    specs = []
    # Balton
    balton = Character.query.filter_by(name = "balton").first()
    specs.append(Specialization(name="protection", role_id=tank.id, gearscore=5145, character_id=balton.id))
    specs.append(Specialization(name="fury", role_id=melee.id, gearscore=4875, character_id=balton.id))
    # Ohval
    ohval =  Character.query.filter_by(name = "ohval").first() 
    specs.append(Specialization(name="Holy", role_id=heal.id, gearscore=5859, character_id=ohval.id))
    specs.append(Specialization(name="Retribution", role_id=melee.id, gearscore=5154, character_id=ohval.id))
    # Bouton
    bouton =  Character.query.filter_by(name = "bouton").first()
    specs.append(Specialization(name="fire", role_id=ranged.id, gearscore=5357, character_id=bouton.id))
    # Huntondis
    hunton = Character.query.filter_by(name = "huntondis").first()
    specs.append(Specialization(name="survival", role_id=ranged.id, gearscore=5354, character_id=hunton.id))
    # Quhzx
    quhzx = Character.query.filter_by(name = "quhzx").first()
    specs.append(Specialization(name="restoration", role_id=heal.id, gearscore=5154, character_id=quhzx.id))
    specs.append(Specialization(name="enhancement", role_id=melee.id, gearscore=4154, character_id=quhzx.id))
    # Milarepa
    mila =  Character.query.filter_by(name = "milarepa").first()
    specs.append(Specialization(name="blood", role_id=tank.id, gearscore=4758, character_id=mila.id))
    specs.append(Specialization(name="unholy", role_id=melee.id, gearscore=4654, character_id=mila.id))
    # Deathtoken
    deathtok =  Character.query.filter_by(name = "deathtoken").first()
    specs.append(Specialization(name="assassination", role_id=melee.id, gearscore=4785, character_id=deathtok.id))
    # Rengekyo
    renge =  Character.query.filter_by(name = "rengekyo").first()
    specs.append(Specialization(name="discipline", role_id=heal.id, gearscore=5124, character_id=renge.id))
    specs.append(Specialization(name="shadow", role_id=ranged.id, gearscore=5154, character_id=renge.id))
    db.session.bulk_save_objects(specs)

    # schedule
    sched = Schedule(player_id=BALTON.id, available = [0,1,1,0,0,1,0])
    db.session.add(sched)
    # check that scheduling works
    check = Schedule.query.filter_by(player_id=BALTON.id).first()
    print(check)
    check.printWeek()
