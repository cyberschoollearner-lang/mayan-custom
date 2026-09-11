from django.utils.translation import gettext_lazy as _

from mayan.apps.smart_settings.setting_clusters import setting_cluster

setting_namespace = setting_cluster.do_namespace_add(
    label=_(message='Custom'), name='custom', version='0001'
)

setting_max_retention_years = setting_namespace.do_setting_add(
    default=5,
    global_name='CUSTOM_MAX_RETENTION_YEARS',
    help_text=_(
        message=(
            'Максимальна кількість років зберігання документів у кабінетах '
            'клінік і клієнтів. Використовується rotate_cabinets.py — папки '
            'старші за цей строк архівуються ({рік}_archive).'
        )
    ),
)

setting_archive_delete_after_days = setting_namespace.do_setting_add(
    default=30,
    global_name='CUSTOM_ARCHIVE_DELETE_AFTER_DAYS',
    help_text=_(
        message=(
            'Через скільки днів після архівації (_archive) папка видаляється '
            'остаточно. Використовується rotate_cabinets.py --cleanup.'
        )
    ),
)

setting_edit_window_hours = setting_namespace.do_setting_add(
    default=12,
    global_name='CUSTOM_EDIT_WINDOW_HOURS',
    help_text=_(
        message=(
            'Скільки годин після 8:00 клініка може перейменовувати і '
            'перезаливати (нова версія) файли, завантажені сьогодні, а також '
            'видаляти їх. Після завершення вікна — тільки перегляд/'
            'завантаження/розшарювання. 12 або 24.'
        )
    ),
)
