from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required


@login_required
def home_redirect(request):
    """
    Після логіну редіректить юзера в його кабінет.
    - AJAX запит (Mayan) → статус 278 + Location header
    - Звичайний запит → стандартний 302 редірект
    Адмін → головна, звичайний юзер → свій кабінет.
    """
    if request.user.is_superuser:
        target_url = reverse('common:home')
    else:
        target_url = reverse('common:home')
        try:
            from mayan.apps.cabinets.models import Cabinet
            cabinet = Cabinet.objects.filter(
                label=request.user.username,
                parent=None
            ).first()
            if cabinet:
                target_url = reverse(
                    'cabinets:cabinet_view',
                    kwargs={'cabinet_id': cabinet.pk}
                )
        except Exception as e:
            print(f'[home_redirect] error: {e}')

    # Перевіряємо чи це AJAX запит від Mayan
    is_ajax = (
        request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
        or request.META.get('HTTP_X_ALT_REFERER')
    )

    if is_ajax:
        response = HttpResponse(status=278)
        response['Location'] = target_url
        return response
    else:
        return HttpResponseRedirect(target_url)

