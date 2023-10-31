from flask import render_template, request, jsonify, redirect, url_for
from .models import db, Player, Schedule, Character
from . import app

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/player', methods=['POST'])
def add_player():
    name = request.form['name']
    new_player = Player(name=name)
    db.session.add(new_player)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/schedule', methods=['POST'])
def add_schedule():
    player_id = request.form['player_id']
    # Assume 'available' is sent as a list of 7 checkboxes where checked is 'on'
    available = [1 if request.form.get(f'day{i}') == 'on' else 0 for i in range(7)]
    new_schedule = Schedule(player_id=player_id, available=available)
    db.session.add(new_schedule)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/character', methods=['POST'])
def add_character():
    name = request.form['name']
    class_name = request.form['class_name']
    player_id = request.form['player_id']
    new_character = Character(name=name, class_name=class_name, player_id=player_id)
    db.session.add(new_character)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/players')
def get_players():
    players = Player.query.all()
    player_data = [{'id': player.id, 'name': player.name, 'discord':player.discord_id, 'piterToken':player.piter_death_tokens} for player in players]
    return jsonify(player_data)

@app.route('/schedules')
def get_schedules():
    schedules = Schedule.query.all()
    schedule_data = [{'id': schedule.id, 'player_id': schedule.player_id, 'available': schedule.available} for schedule in schedules]
    return jsonify(schedule_data)

@app.route('/characters')
def get_characters():
    characters = Character.query.all()
    character_data = [{'id': character.id, 'name': character.name, 'class_name': character.class_name, 'player_id': character.player_id} for character in characters]
    return jsonify(character_data)
    
