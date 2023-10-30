from app import app, db
from app.models import Player, Character, Specialization, Buff
from app.data import load_guild
# Create a command line command to initialize the database
@app.cli.command('db_create')
def db_create():
    with app.app_context():
        db.create_all()
        print("Database created!")

# Create a command line command to drop the database
@app.cli.command('db_drop')
def db_drop():
    with app.app_context():
        db.drop_all()
        print("Database dropped!")

# Create a command line command to seed the database
@app.cli.command('db_seed')
def db_seed():
    with app.app_context():
        load_guild()
        
        print("Database seeded!")
    

if __name__ == '__main__':
    app.run(debug=True)
    # with app.app_context():
    #     db.create_all()
    #     print('created database')
