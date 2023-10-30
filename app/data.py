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
    roles.append(Role(name = "Tank"))
    roles.append(Role(name="Melee"))
    roles.append(Role(name="Ranged"))
    roles.append(Role(name="Heals"))
    db.session.bulk_save_objects(roles)
    
def load_deego():
    newDeego = Player(name = "Deego")
    db.session.add(newDeego)
    DEEGO =  Player.query.filter_by(name = "Deego").first()
    # Add Deego Characters
    cities =  Character(name = "Cities", class_name = "Paladin", player_id = DEEGO.id)
    wynt =  Character(name = "Wynt", class_name = "Mage", player_id = DEEGO.id)
    trumble = Character(name = "Trumble", class_name = "Hunter", player_id = DEEGO.id)
    deego = Character(name = "Deego", class_name = "Shaman", player_id = DEEGO.id)
    blacky =  Character(name = "Blackthorn", class_name = "Death Knight", player_id = DEEGO.id)
    hams =  Character(name = "Steamedhams", class_name = "Druid", player_id = DEEGO.id)
    sayno =  Character(name = "Saynotozugs", class_name = "Priest", player_id = DEEGO.id)
    db.session.add(cities)
    db.session.add(wynt)
    db.session.add(deego)
    db.session.add(trumble)
    db.session.add(blacky)
    db.session.add(hams)
    db.session.add(sayno)
    
    
def load_balton():
    # Seed info with Players
    newBalton = Player(name = "Balton")
    db.session.add(newBalton)
    BALTON = Player.query.filter_by(name = "Balton").first()
    tank = Role.query.filter_by(name = "Tank").first()
    heal = Role.query.filter_by(name = "Heals").first()
    melee = Role.query.filter_by(name = "Melee").first()
    ranged = Role.query.filter_by(name = "Ranged").first()
    
    # Add Balton Characters
    balton = Character(name = "Balton", class_name = "Warrior", player_id = BALTON.id)
    ohval =  Character(name = "Ohval", class_name = "Paladin", player_id = BALTON.id)
    bouton =  Character(name = "Bouton", class_name = "Mage", player_id = BALTON.id)
    hunton = Character(name = "Huntondis", class_name = "Hunter", player_id = BALTON.id)
    quhzx = Character(name = "Quhzx", class_name = "Shaman", player_id = BALTON.id)
    mila =  Character(name = "Milarepa", class_name = "Death Knight", player_id = BALTON.id)
    deathtok =  Character(name = "Deathtoken", class_name = "Rogue", player_id = BALTON.id)
    renge =  Character(name = "Rengekyo", class_name = "Priest", player_id = BALTON.id)
    
    db.session.add(balton)
    db.session.add(quhzx)
    db.session.add(ohval)
    db.session.add(bouton)
    db.session.add(hunton)
    db.session.add(mila)
    db.session.add(deathtok)
    db.session.add(renge)

    # character Specializations
    specs = []
    # Balton
    balton = Character.query.filter_by(name = "Balton").first()
    specs.append(Specialization(name="Protection", role_id=tank.id, gearscore=5145, character_id=balton.id))
    specs.append(Specialization(name="Fury", role_id=melee.id, gearscore=4875, character_id=balton.id))
    # Ohval
    ohval =  Character.query.filter_by(name = "Ohval").first() 
    specs.append(Specialization(name="Holy", role_id=heal.id, gearscore=5859, character_id=ohval.id))
    specs.append(Specialization(name="Retribution", role_id=melee.id, gearscore=5154, character_id=ohval.id))
    # Bouton
    bouton =  Character.query.filter_by(name = "Bouton").first()
    specs.append(Specialization(name="Fire", role_id=ranged.id, gearscore=5357, character_id=bouton.id))
    # Huntondis
    hunton = Character.query.filter_by(name = "Huntondis").first()
    specs.append(Specialization(name="Survival", role_id=ranged.id, gearscore=5354, character_id=hunton.id))
    # Quhzx
    quhzx = Character.query.filter_by(name = "Quhzx").first()
    specs.append(Specialization(name="Restoration", role_id=heal.id, gearscore=5154, character_id=quhzx.id))
    specs.append(Specialization(name="Enhancement", role_id=melee.id, gearscore=4154, character_id=quhzx.id))
    # Milarepa
    mila =  Character.query.filter_by(name = "Milarepa").first()
    specs.append(Specialization(name="Blood", role_id=tank.id, gearscore=4758, character_id=mila.id))
    specs.append(Specialization(name="Unholy", role_id=melee.id, gearscore=4654, character_id=mila.id))
    # Deathtoken
    deathtok =  Character.query.filter_by(name = "Deathtoken").first()
    specs.append(Specialization(name="Assassination", role_id=melee.id, gearscore=4785, character_id=deathtok.id))
    # Rengekyo
    renge =  Character.query.filter_by(name = "Rengekyo").first()
    specs.append(Specialization(name="Discipline", role_id=heal.id, gearscore=5124, character_id=renge.id))
    specs.append(Specialization(name="Shadow", role_id=ranged.id, gearscore=5154, character_id=renge.id))
    db.session.bulk_save_objects(specs)

    # schedule
    sched = Schedule(player_id=BALTON.id, available = [0,1,1,0,0,1,0])
    db.session.add(sched)
    # check that scheduling works
    # check = Schedule.query.filter_by(player_id=BALTON.id).first()
    # print(check)
    # check.printWeek()
