import threading
from django.shortcuts import redirect
from django.urls import reverse

_thread_local = threading.local()


def get_current_user():
    return getattr(_thread_local, 'current_user', None)


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_local.current_user = getattr(request, 'user', None)
        response = self.get_response(request)
        return response


class CabinetRedirectMiddleware:
    """
    Після логіну редіректить звичайного юзера одразу в його кабінет.
    Адмін (is_superuser) потрапляє на звичайну головну сторінку.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Перехоплюємо редірект після логіну
        if (
            response.status_code == 302
            and request.path == '/authentication/login/'
            and request.user.is_authenticated
            and not request.user.is_superuser
        ):
            try:
                from mayan.apps.cabinets.models import Cabinet
                cabinet = Cabinet.objects.filter(
                    label=request.user.username,
                    parent=None
                ).first()

                if cabinet:
                    url = reverse(
                        'cabinets:cabinet_view',
                        kwargs={'cabinet_id': cabinet.pk}
                    )
                    return redirect(url)
            except Exception:
                pass

        return response
