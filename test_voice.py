import urllib.request
import json

boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
body = (
    f"--{boundary}\r\n"
    f"Content-Disposition: form-data; name=\"audio\"; filename=\"audio.webm\"\r\n"
    f"Content-Type: audio/webm\r\n\r\n"
    f"dummy_audio_bytes\r\n"
    f"--{boundary}--\r\n"
).encode('utf-8')

req = urllib.request.Request(
    'http://localhost:8000/api/voice/transcribe',
    data=body,
    headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}
)
try:
    print(urllib.request.urlopen(req).read().decode())
except Exception as e:
    try:
        print("Error:", e.read().decode())
    except:
        print("Error:", e)
