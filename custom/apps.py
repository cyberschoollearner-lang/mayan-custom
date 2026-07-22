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

    @classmethod
    def get_template_dirs(cls):
        return [os.path.join(os.path.dirname(__file__), 'templates')]
