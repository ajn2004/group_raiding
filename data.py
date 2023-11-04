import json
from app import app
from app.models import *

with open('data/loot-data.json', 'r') as json_file:
    data = json.load(json_file)


count = 0
rogat = data['rogat']
for item in rogat['received']:
    if item['name'] == 'Shadowfrost Shard':
        count += 1
print('Rogat has recieved ' + str(count) + ' shards so far out of 50')
