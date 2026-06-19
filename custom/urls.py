from django.urls import re_path
from . import views

urlpatterns = [
    re_path(
        route=r'^home/$',
        name='home_redirect',
        view=views.home_redirect
    ),
]

