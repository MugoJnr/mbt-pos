from pathlib import Path
p = Path(r'C:\Users\mugoj\OneDrive\Desktop\MBT POS\extracted\mbt_pos\desktop\utils\pos_components.py')
t = p.read_text(encoding='utf-8')
old = 'card_size = (248, 102) if self._is_light else (236, 98)'
new = 'card_size = (248, 118) if self._is_light else (236, 114)'
if old not in t:
    print('pattern missing')
else:
    t = t.replace(old, new, 1)
    p.write_text(t, encoding='utf-8')
    print('updated card_size')
t2 = p.read_text(encoding='utf-8')
print('has table density total', "self._density == 'table'" in t2 and 'tot:,.2f' in t2)
print('has min width 96', 'setMinimumWidth(96)' in t2)
print('has remove x', "QPushButton('×')" in t2 or 'QPushButton("×")' in t2)
