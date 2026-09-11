python3 << 'PYEOF'
path = '/opt/mayan/custom/apps.py'
with open(path) as f:
    content = f.read()

# Знаходимо метод і конвертуємо його відступи tabs->8 spaces, потім усі в стандартні 4-space Python
import re
# Простіше: замінюємо ВСІ таби в файлі на 4 пробіли послідовно
content = content.expandtabs(4)

with open(path, 'w') as f:
    f.write(content)

print('Конвертовано таби -> пробіли')
PYEOF

python3 -m py_compile /opt/mayan/custom/apps.py && echo "OK: синтаксис валідний"
