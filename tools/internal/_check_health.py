import requests, json, sys
sys.stdout.reconfigure(encoding='utf-8')
r = requests.get('http://localhost:8000/health', timeout=30)
data = r.json()
components = data['payload']['components']
print(f"Total components: {len(components)}")
for i, c in enumerate(components):
    try:
        print(f'[{i}] {c["component"]}: {c["status"]} - {c["message"]}')
    except Exception as e:
        print(f'[{i}] ERROR printing: {e}')
        print(f'[{i}] Raw: {json.dumps(c, ensure_ascii=True)}')
