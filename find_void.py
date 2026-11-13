import re

content = open('web/web_routes.py', encoding='utf-8', errors='ignore').read()
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'void' in line.lower() and ('route' in line.lower() or 'api' in line.lower()):
        print(f'{i+1}: {line.strip()}')