from django.apps import AppConfig
import os


class CustomConfig(AppConfig):
    name = 'custom'

    def ready(self):
        import custom.signals  # noqa


    @classmethod
    def get_template_dirs(cls):
        return [os.path.join(os.path.dirname(__file__), 'templates')]
