from mayan.apps.app_manager.apps import MayanAppConfig
import os


class CustomConfig(MayanAppConfig):
    name = 'custom'
    app_url = 'custom'
    app_namespace = 'custom'

    def ready(self):
        super().ready()
        import custom.signals  # noqa
        self._remove_columns()
        self._remove_duplicate_backend_label()
        self._ensure_storage_permissions()

    def _remove_columns(self):
        try:
            from mayan.apps.navigation.source_columns import SourceColumn
            from mayan.apps.documents.models import (
                Document, DocumentFile, DocumentVersion,
                DocumentFilePage, DocumentVersionPage
            )

            REMOVE_LABELS = {
                'Thumbnail', 'Type', 'Metadata', 'Pages', 'Tags',
            }

            for source in (Document, DocumentFile, DocumentVersion,
                           DocumentFilePage, DocumentVersionPage):
                if source in SourceColumn._registry:
                    SourceColumn._registry[source] = [
                        col for col in SourceColumn._registry[source]
                        if col.__dict__.get('label', '') not in REMOVE_LABELS
                    ]

        except Exception as e:
            print(f'[CUSTOM] remove_columns error: {e}')

    def _remove_duplicate_backend_label(self):
        # Прибираємо DuplicateBackendLabel з реєстру backend-класів,
        # щоб Mayan не пересинхронізовував його назад у StoredDuplicateBackend
        # після кожного імпорту/завантаження документа.
        # Залишається лише DuplicateBackendFileChecksum (перевірка по чексумі).
        try:
            from mayan.apps.duplicates.classes import DuplicateBackendMetaclass

            label_key = (
                'mayan.apps.duplicates.duplicate_backends.'
                'DuplicateBackendLabel'
            )
            DuplicateBackendMetaclass._registry.pop(label_key, None)
        except Exception as e:
            print(f'[CUSTOM] remove_duplicate_backend_label error: {e}')

    def _ensure_storage_permissions(self):
        """
        Перевіряє, що критичні storage-каталоги належать процесу mayan
        (uid 1000), і попереджає в лог, якщо ні. Не робить chown автоматично:
        на 900k+ файлів це було б повільно й ризиковано робити мовчки при
        кожному старті контейнера кількома воркерами паралельно.

        Симптом проблеми: якщо document_storage належить root, Celery-worker
        (працює під mayan) не може ні писати нові файли, ні видаляти їх
        з кошика — PermissionError. Фікс вручну:

            docker exec mayan-app-1 chown mayan:mayan /var/lib/mayan/document_storage
        """
        import pwd
        try:
            expected_uid = pwd.getpwnam('mayan').pw_uid
        except KeyError:
            return

        paths_to_check = [
            '/var/lib/mayan/document_storage',
        ]
        for path in paths_to_check:
            try:
                st = os.stat(path)
                if st.st_uid != expected_uid:
                    print(
                        f'[CUSTOM] WARNING: {path} має uid={st.st_uid}, '
                        f'очікувалось {expected_uid} (mayan). '
                        f'Виконай: docker exec mayan-app-1 chown mayan:mayan {path}'
                    )
            except FileNotFoundError:
                pass

    @classmethod
    def get_template_dirs(cls):
        return [os.path.join(os.path.dirname(__file__), 'templates')]
