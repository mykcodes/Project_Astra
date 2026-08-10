import urllib.request
import json

req = urllib.request.Request(
    'http://localhost:8000/api/conversation/message', 
    data=json.dumps({'text':'hi'}).encode(), 
    headers={'Content-Type': 'application/json'}
)
try: 
    print(urllib.request.urlopen(req).read().decode()) 
except Exception as e: 
    try:
        print(e.read().decode())
    except:
        print(e)
