import json

with open('data/character-json.json', 'r') as json_file:
    data = json.load(json_file)

outjson = {}
for item in data:
    outjson[item['slug']] = item

with open('data/loot-data.json', 'w+') as json_file:
    json_file.write(json.dumps(outjson))
