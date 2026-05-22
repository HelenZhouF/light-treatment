import urllib.request
import json

print('=== 测试完整视图 ===')
resp = urllib.request.urlopen('http://localhost:8005/treatmentDefinition/definitions/1')
data = json.loads(resp.read())
print(f'Content-Type: {resp.headers.get("content-type")}')
print(f'包含 attributes: {"attributes" in data}')
print(f'字段数量: {len(data)}')

print('\n=== 测试 summary 视图 (view=summary) ===')
resp = urllib.request.urlopen('http://localhost:8005/treatmentDefinition/definitions/1?view=summary')
data = json.loads(resp.read())
print(f'Content-Type: {resp.headers.get("content-type")}')
print(f'包含 attributes: {"attributes" in data}')
print(f'字段: {list(data.keys())}')

print('\n=== 测试 summary 视图 (Accept-Item) ===')
req = urllib.request.Request('http://localhost:8005/treatmentDefinition/definitions/1')
req.add_header('Accept-Item', 'application/vnd.sas.summary+json')
resp = urllib.request.urlopen(req)
data = json.loads(resp.read())
print(f'Content-Type: {resp.headers.get("content-type")}')
print(f'包含 attributes: {"attributes" in data}')

print('\n=== 测试 revisionSummary 视图 ===')
resp = urllib.request.urlopen('http://localhost:8005/treatmentDefinition/definitions/1?view=revisionSummary')
data = json.loads(resp.read())
print(f'Content-Type: {resp.headers.get("content-type")}')
print(f'字段: {list(data.keys())}')
