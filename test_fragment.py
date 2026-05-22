import urllib.request
import json

print('=== 测试 URI fragment #summary ===')
url = 'http://localhost:8005/treatmentDefinition/definitions/1#summary'
print(f'请求: {url}')
resp = urllib.request.urlopen(url)
data = json.loads(resp.read())
print(f'Content-Type: {resp.headers.get("content-type")}')
print(f'包含 attributes: {"attributes" in data}')

print('\n=== 测试 URI fragment #revisionSummary ===')
url = 'http://localhost:8005/treatmentDefinition/definitions/1#revisionSummary'
print(f'请求: {url}')
resp = urllib.request.urlopen(url)
data = json.loads(resp.read())
print(f'Content-Type: {resp.headers.get("content-type")}')
print(f'字段: {list(data.keys())}')
