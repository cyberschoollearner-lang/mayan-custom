import re

with open('README.md', encoding='utf-8') as f:
    text = f.read()
with open('custom/apps.py', encoding='utf-8') as f:
    apps_py = f.read().rstrip('\n')
with open('custom/templates/appearance/menus/topbar.html', encoding='utf-8') as f:
    topbar_html = f.read().rstrip('\n')
with open('scripts/backups.sh', encoding='utf-8') as f:
    backups_sh = f.read().rstrip('\n')

def replace_code_block(text, heading, new_code, lang):
    pattern = re.compile(re.escape(heading) + r'\n\n```' + re.escape(lang) + r'\n.*?\n```', re.DOTALL)
    replacement = heading + '\n\n```' + lang + '\n' + new_code + '\n```'
    new_text, n = pattern.subn(replacement, text, count=1)
    print(f'[OK] {heading}' if n else f'[WARN] не знайдено: {heading}')
    return new_text

text = replace_code_block(text, '### `/opt/mayan/custom/apps.py`', apps_py, 'python')
text = replace_code_block(text, '### `/opt/mayan/custom/templates/appearance/menus/topbar.html`', topbar_html, 'html')

pattern = re.compile(r'### `backup\.sh`\n\n```bash\n.*?\n```', re.DOTALL)
replacement = '### `backups.sh`\n\n```bash\n' + backups_sh + '\n```'
text, n = pattern.subn(replacement, text, count=1)
print('[OK] backup.sh -> backups.sh' if n else '[WARN] не знайдено backup.sh')

old_note = ('> **Важливо:** після оновлення Mayan цей запис може відновитись. '
            'Перевіряй після кожного оновлення.')
new_note = ('> **Важливо:** Mayan автоматично реєструє `DuplicateBackendLabel` назад у реєстр '
            '(`DuplicateBackendMetaclass._registry`) при кожному скануванні документа (імпорт, '
            'веб-завантаження), тому одноразове видалення з БД не є стійким. Постійний фікс '
            'зроблено в `custom/apps.py` методом `_remove_duplicate_backend_label()` (див. вище) — '
            'він прибирає клас з реєстру при кожному старті додатку, і Mayan більше не може '
            'пересинхронізувати його назад.')
if old_note in text:
    text = text.replace(old_note, new_note)
    print('[OK] нотатка про дублікати оновлена')
else:
    print('[WARN] стару нотатку не знайдено')

search_section = '''---

## Розширення полів пошуку (Filter terms / Search terms)

За замовчуванням Bootstrap-навбар звужує `.form-control` до вузької ширини. Поле **Filter terms**
(список документів, `dynamic_search/app/list_toolbar.html`) і **Search terms** (навбар,
`dynamic_search/search_box_toolbar.html`) — обидва прив'язані до реального search backend
(не client-side фільтр), тому обмеження стосується лише візуальної ширини.

Розширено через CSS-override у `custom/templates/appearance/menus/topbar.html`:

```css
#search-filter-input-terms { width: 100% !important; min-width: 320px; }
#search-navbar-form-input-terms { width: 320px !important; }
@media (min-width: 1200px) {
    #search-navbar-form-input-terms { width: 450px !important; }
}
```

---

## Затримка індексації після імпорту

Документи, додані через `import_clinic.py` (в т.ч. `[LINK]` — прив'язка існуючого документа
до нового кабінету по checksum), можуть не з'являтись у результатах пошуку одразу — індексація
йде асинхронно через Celery. Це очікувана поведінка, не помилка.

'''
if 'Розширення полів пошуку' not in text:
    text = text.replace('## HTTPS', search_section + '## HTTPS', 1)
    print('[OK] додано секції про пошук і затримку індексації')
else:
    print('[SKIP] секція вже є')

with open('README.md', 'w', encoding='utf-8') as f:
    f.write(text)
print('\n=== ГОТОВО ===')
