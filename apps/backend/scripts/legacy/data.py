import json
from pathlib import Path

with (Path(__file__).resolve().parents[2] / 'data' / 'loot-data.json').open('r') as json_file:
    data = json.load(json_file)

toon = 'TOON_NAME'
count = 0
loot = data['toon']
for item in loot['received']:
    if item['name'] == 'Shadowfrost Shard':
        count += 1
print(toon + ' has recieved ' + str(count) + ' shards so far out of 50')
