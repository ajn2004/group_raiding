import json
from app import app
from app.models import *

with open('data/loot-data.json', 'r') as json_file:
    data = json.load(json_file)

toon = 'TOON_NAME'
count = 0
loot = data['toon']
for item in loot['received']:
    if item['name'] == 'Shadowfrost Shard':
        count += 1
print(toon + ' has recieved ' + str(count) + ' shards so far out of 50')
