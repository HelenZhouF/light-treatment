import urllib.request
import json
import sys
import urllib.parse

base_url = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:8004/treatmentDefinition/definitions'
filter_param = sys.argv[2] if len(sys.argv) > 2 else None

if filter_param:
    url = f"{base_url}?filter={urllib.parse.quote(filter_param)}"
else:
    url = base_url

print(f'Testing: {url}')
try:
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read())
    print(f'Count: {data["count"]}')
    for item in data['items']:
        print(f'  id={item["id"]}, name={item["name"]}')
except urllib.error.HTTPError as e:
    print(f'HTTP Error: {e.code} {e.reason}')
    print(e.read().decode())
except Exception as e:
    print(f'Error: {e}')
