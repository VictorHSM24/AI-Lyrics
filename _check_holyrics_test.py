import requests, json, sys
sys.stdout.reconfigure(encoding='utf-8')

# Test with correct port (8091)
print("=== Test Holyrics port 8091 (correct) ===")
r = requests.post('http://localhost:8000/health/holyrics/test', json={
    'base_url': 'http://127.0.0.1:8091/api',
    'token': 'JCpH5Wn4Q4zi7og0',
}, timeout=10)
data = r.json()
print(f"ok: {data['payload']['ok']}")
print(f"message: {data['payload']['message']}")
print(f"latency_ms: {data['payload'].get('latency_ms')}")

# Test with wrong port (8080)
print("\n=== Test Holyrics port 8080 (wrong) ===")
r = requests.post('http://localhost:8000/health/holyrics/test', json={
    'base_url': 'http://127.0.0.1:8080/api',
    'token': 'JCpH5Wn4Q4zi7og0',
}, timeout=10)
data = r.json()
print(f"ok: {data['payload']['ok']}")
print(f"message: {data['payload']['message']}")
print(f"latency_ms: {data['payload'].get('latency_ms')}")

# Test with wrong token
print("\n=== Test Holyrics wrong token ===")
r = requests.post('http://localhost:8000/health/holyrics/test', json={
    'base_url': 'http://127.0.0.1:8091/api',
    'token': 'wrongtoken',
}, timeout=10)
data = r.json()
print(f"ok: {data['payload']['ok']}")
print(f"message: {data['payload']['message']}")
print(f"latency_ms: {data['payload'].get('latency_ms')}")
