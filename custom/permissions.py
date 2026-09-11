from django.utils.translation import gettext_lazy as _

from mayan.apps.permissions.classes import PermissionNamespace

namespace = PermissionNamespace(
    label=_(message='Custom'), name='custom'
)

permission_document_direct_download = namespace.add_permission(
    label=_(message='Direct download document on click (skip preview)'),
    name='custom_document_direct_download',
)
