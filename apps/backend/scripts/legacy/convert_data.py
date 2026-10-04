import json
from pathlib import Path

data_dir = Path(__file__).resolve().parents[2] / 'data'
with (data_dir / 'character-json.json').open('r') as json_file:
    data = json.load(json_file)

outjson = {}
for item in data:
    outjson[item['slug']] = item

with (data_dir / 'loot-data.json').open('w+') as json_file:
    json_file.write(json.dumps(outjson))
