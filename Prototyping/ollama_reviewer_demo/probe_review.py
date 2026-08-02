import json
import urllib.request

req = urllib.request.Request(
    'http://127.0.0.1:8000/api/reviewer/review',
    data=json.dumps({
        'model': 'llama3.2:3b',
        'skills_prompt': 'test',
        'review_goal': 'test',
        'document_text': 'test'
    }).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST'
)

with urllib.request.urlopen(req, timeout=20) as response:
    print(response.read().decode())
