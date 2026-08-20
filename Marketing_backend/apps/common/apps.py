from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = 'apps.common'

    def ready(self):
        # Registers the deployment safety checks with Django's check framework.
        from . import checks  # noqa: F401
