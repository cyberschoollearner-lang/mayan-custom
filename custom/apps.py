import os

from mayan.apps.app_manager.apps import MayanAppConfig


class CustomConfig(MayanAppConfig):
    name = 'custom'
    app_url = 'custom'
    app_namespace = 'custom'

    def ready(self):
        super().ready()
        import custom.signals  # noqa
        import custom.settings  # noqa
        # Реєструє CUSTOM_MAX_RETENTION_YEARS,
        # CUSTOM_ARCHIVE_DELETE_AFTER_DAYS, CUSTOM_EDIT_WINDOW_HOURS
        import custom.permissions

        self._remove_columns()
        self._remove_duplicate_backend_label()
        self._ensure_storage_permissions()
        self._restrict_menus_for_clients()
        self._force_list_mode_default()
        self._patch_document_click_to_download()
        self._restrict_left_menu_for_clients()

    def _remove_columns(self):
        try:
            from mayan.apps.navigation.source_columns import SourceColumn
            from mayan.apps.documents.models import (
                Document,
                DocumentFile,
                DocumentVersion,
                DocumentFilePage,
                DocumentVersionPage,
            )

            REMOVE_LABELS = {
                'Thumbnail',
                'Type',
                'Metadata',
                'Pages',
                'Tags',
            }

            for source in (
                Document,
                DocumentFile,
                DocumentVersion,
                DocumentFilePage,
                DocumentVersionPage,
            ):
                if source in SourceColumn._registry:
                    SourceColumn._registry[source] = [
                        col
                        for col in SourceColumn._registry[source]
                        if col.__dict__.get('label', '') not in REMOVE_LABELS
                    ]

        except Exception as e:
            print(f'[CUSTOM] remove_columns error: {e}')

    def _remove_duplicate_backend_label(self):
        """
        Прибираємо DuplicateBackendLabel з реєстру backend-класів,
        щоб Mayan не пересинхронізовував його назад у
        StoredDuplicateBackend після кожного імпорту/завантаження документа.

        Залишається лише DuplicateBackendFileChecksum
        (перевірка по чексумі).
        """
        try:
            from mayan.apps.duplicates.classes import DuplicateBackendMetaclass

            label_key = (
                'mayan.apps.duplicates.duplicate_backends.'
                'DuplicateBackendLabel'
            )

            DuplicateBackendMetaclass._registry.pop(label_key, None)

        except Exception as e:
            print(
                f'[CUSTOM] remove_duplicate_backend_label error: {e}'
            )

    def _ensure_storage_permissions(self):
        """
        Перевіряє, що критичні storage-каталоги належать процесу mayan
        (uid 1000), і попереджає в лог, якщо ні.

        Не робить chown автоматично: на 900k+ файлів це було б повільно
        й ризиковано робити мовчки при кожному старті контейнера
        кількома воркерами паралельно.

        Симптом проблеми: якщо document_storage належить root,
        Celery-worker (працює під mayan) не може ні писати нові файли,
        ні видаляти їх з кошика.

        Фікс вручну:

            docker exec mayan-app-1 chown mayan:mayan \
                /var/lib/mayan/document_storage
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
                        f'Виконай: docker exec mayan-app-1 '
                        f'chown mayan:mayan {path}'
                    )

            except FileNotFoundError:
                pass

    def _restrict_menus_for_clients(self):
        """
        Приховує menu_object (Actions-дропдаун на одному документі) і
        menu_multi_item ("Дії з набором" — bulk actions при виборі
        чекбоксом) для клієнтів (01000-09999, 5-значний username).

        Клініки (0100-0999) і адмін бачать меню як завжди.
        """
        try:
            from mayan.apps.common.menus import (
                menu_object,
                menu_multi_item,
            )

            def make_client_hides_menu(original_condition):
                def condition(context, resolved_object=None):
                    if original_condition and not original_condition(
                        context=context,
                        resolved_object=resolved_object,
                    ):
                        return False

                    request = context.get('request')
                    user = (
                        getattr(request, 'user', None)
                        if request
                        else None
                    )
                    username = getattr(user, 'username', None)

                    if (
                        username
                        and username.isdigit()
                        and len(username) == 5
                    ):
                        return False

                    return True

                return condition

            menu_object.condition = make_client_hides_menu(
                menu_object.condition
            )

            menu_multi_item.condition = make_client_hides_menu(
                menu_multi_item.condition
            )

        except Exception as e:
            print(
                f'[CUSTOM] restrict_menus_for_clients error: {e}'
            )

    def _force_list_mode_default(self):
        """
        Форсує LIST_MODE_CHOICE_LIST (список) як дефолт для НОВИХ
        записів UserViewMode на всіх view, ігноруючи власний default_mode
        кожного View.

        Деякі View, як-от Cabinets/Documents, за замовчуванням
        дефолтять у плитку.

        Стосується тільки get_or_create() — якщо запис уже існує
        (юзер уже відвідував цей view раніше), його НЕ чіпає.
        """
        try:
            from mayan.apps.views.view_mixins import ListModeViewMixin
            from mayan.apps.views.literals import (
                LIST_MODE_CHOICE_LIST,
                LIST_MODE_CHOICE_ITEM,
                TEXT_LIST_AS_ITEMS_VARIABLE_NAME,
                TEXT_LIST_AS_ITEMS_PARAMETER,
            )
            from mayan.apps.views.models import UserViewMode

            original_get_context_data = (
                ListModeViewMixin.get_context_data
            )

            def patched_get_context_data(self, **kwargs):
                context = original_get_context_data(
                    self,
                    **kwargs,
                )

                return context

            # Прямий патч логіки замість дублювання всього методу:
            # підміняємо саму функцію повністю, з форсованим default_mode.
            def new_get_context_data(self, **kwargs):
                # Викликаємо батьківський клас
                # (минаючи ListModeViewMixin), щоб отримати
                # "сирий" контекст без втручання оригінального mixin.
                context = super(
                    ListModeViewMixin,
                    self,
                ).get_context_data(**kwargs)

                # ЗАВЖДИ форсуємо список як дефолт для нових записів,
                # незалежно від того, що View поклав у
                # TEXT_LIST_AS_ITEMS_VARIABLE_NAME.
                default_mode = LIST_MODE_CHOICE_LIST

                user_list_mode = self.request.GET.get(
                    TEXT_LIST_AS_ITEMS_PARAMETER
                )

                resolver_match = self.request.resolver_match

                view_name = '{}:{}'.format(
                    resolver_match.namespace,
                    resolver_match.url_name,
                )

                if user_list_mode:
                    UserViewMode.objects.update_or_create(
                        defaults={
                            'namespace': resolver_match.namespace,
                            'value': user_list_mode,
                        },
                        name=view_name,
                        user=self.request.user,
                    )

                    final_list_mode = user_list_mode

                else:
                    user_view_mode, created = (
                        UserViewMode.objects.get_or_create(
                            defaults={
                                'namespace': resolver_match.namespace,
                                'value': default_mode,
                            },
                            name=view_name,
                            user=self.request.user,
                        )
                    )

                    final_list_mode = user_view_mode.value

                context.update(
                    {
                        TEXT_LIST_AS_ITEMS_VARIABLE_NAME:
                            final_list_mode == LIST_MODE_CHOICE_ITEM
                    }
                )

                return context

            ListModeViewMixin.get_context_data = new_get_context_data

        except Exception as e:
            print(
                f'[CUSTOM] force_list_mode_default error: {e}'
            )

    def _patch_document_click_to_download(self):
        """
        SourceColumn.resolve() викликає obj.get_absolute_url()
        без доступу до request.

        Замість патчу моделі — патчимо сам SourceColumn.resolve(),
        де context['request'] доступний напряму.

        Якщо request.user має permission
        custom_document_direct_download на документ —
        self.get_absolute_url підміняється на прямий download URL
        замість стандартного Preview.
        """
        try:
            from mayan.apps.navigation.source_columns import SourceColumn
            from mayan.apps.documents.models.document_models import Document
            from mayan.apps.acls.models import AccessControlList
            from custom.permissions import (
                permission_document_direct_download,
            )
            from django.urls import reverse

            original_resolve = SourceColumn.resolve

            def patched_resolve(self, context):
                obj = context.get('object')

                if (
                    isinstance(obj, Document)
                    and self.is_object_absolute_url
                    and obj.file_latest
                ):
                    request = None

                    try:
                        request = self.get_request(
                            context=context
                        )
                    except Exception:
                        pass

                    user = (
                        getattr(request, 'user', None)
                        if request
                        else None
                    )

                    if (
                        user is not None
                        and getattr(
                            user,
                            'is_authenticated',
                            False,
                        )
                    ):
                        try:
                            AccessControlList.objects.check_access(
                                obj=obj,
                                permission=(
                                    permission_document_direct_download
                                ),
                                user=user,
                            )

                            original_get_absolute_url = (
                                self.get_absolute_url
                            )

                            def temp_get_absolute_url(obj=None):
                                return reverse(
                                    viewname=(
                                        'document_downloads:'
                                        'document_file_download'
                                    ),
                                    kwargs={
                                        'document_file_id': (
                                            obj.file_latest.pk
                                        )
                                    },
                                )

                            self.get_absolute_url = (
                                temp_get_absolute_url
                            )

                            try:
                                result = original_resolve(
                                    self,
                                    context,
                                )
                            finally:
                                self.get_absolute_url = (
                                    original_get_absolute_url
                                )

                            return result

                        except Exception:
                            pass
                            pass

                return original_resolve(
                    self,
                    context,
                )

            SourceColumn.resolve = patched_resolve

        except Exception as e:
            print(
                f'[CUSTOM] patch_document_click_to_download error: {e}'
            )

    def _restrict_left_menu_for_clients(self):
        """
        Для клієнтів (01000-09999, 5-значний username):
        - menu_documents повністю приховується (весь підменю "Документи")
        - замість нього прямий Link "Всі документи" без розкриття
        - menu_cabinets ("Шафи") повністю приховується
        - "Дублікати" (menu_documents) і "Перевірки" (menu_main) приховуються
        - додається пункт "Головна" в menu_main
        Клініки/адмін бачать меню без змін.
        """
        try:
            from mayan.apps.documents.menus import menu_documents
            from mayan.apps.cabinets.menus import menu_cabinets
            from mayan.apps.documents.links.document_links import link_document_list
            from mayan.apps.common.menus import menu_main
            from mayan.apps.navigation.links import Link
            from django.utils.translation import gettext_lazy as _
            from mayan.apps.checkouts.links import link_check_out_list

            def is_client(context):
                request = context.get('request')
                user = getattr(request, 'user', None) if request else None
                username = getattr(user, 'username', None)
                return bool(username and username.isdigit() and len(username) == 5)

            def make_hide_for_clients(original_condition):
                def condition(context, resolved_object=None):
                    if is_client(context):
                        return False
                    if original_condition:
                        return original_condition(context=context)
                    return True
                return condition

            # Ховаємо цілі підменю "Документи" і "Шафи" для клієнтів
            menu_documents.condition = make_hide_for_clients(menu_documents.condition)
            menu_cabinets.condition = make_hide_for_clients(menu_cabinets.condition)
            link_check_out_list.condition = make_hide_for_clients(link_check_out_list.condition)

            # Прямий Link "Всі документи" — видно ТІЛЬКИ клієнтам
            # (протилежна умова: показуємо, якщо is_client)
            def show_only_for_clients(context, resolved_object=None):
                return is_client(context)

            link_all_documents_direct = Link(
                text=_(message='Всі документи'),
                view='documents:document_list',
                condition=show_only_for_clients,
            )
            menu_main.bind_links(links=(link_all_documents_direct,), position=10)

            # "Головна"
            link_custom_home = Link(
                text=_(message='Головна'), view='custom:home_redirect'
            )
            menu_main.bind_links(links=(link_custom_home,), position=0)

        except Exception as e:
            print(f'[CUSTOM] restrict_left_menu_for_clients error: {e}')

    @classmethod
    def get_template_dirs(cls):
        return [
            os.path.join(
                os.path.dirname(__file__),
                'templates',
            )
        ]

