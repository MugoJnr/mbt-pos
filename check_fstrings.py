import re

content = open('web/web_routes.py').read()
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'f"' in line and ('SELECT' in line or 'INSERT' in line or 'UPDATE' in line or 'DELETE' in line):
        print(f'{i+1}: {line.strip()}')