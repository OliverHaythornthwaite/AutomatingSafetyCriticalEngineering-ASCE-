import json
import urllib.request

payload = {"model": "llama3.2:3b", "prompt": "ping", "stream": False}
req = urllib.request.Request(
    "http://127.0.0.1:11434/api/generate",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=60) as r:
        print(r.read().decode())
except Exception as e:
    print(type(e).__name__, e)
