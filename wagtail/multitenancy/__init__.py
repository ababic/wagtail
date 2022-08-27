import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wagtail.models import Tenant


def get_default_tenant_id() -> int:
    from django.conf import settings

    return getattr(settings, "WAGTAIL_DEFAULT_TEANANT", 1)


def get_active_tenant() -> "Tenant":
    """
    If ``wagtail.multitenancy.middleware.ActiveTenantMiddleware`` is enabled,
    this function returns the ``Tenant`` object already identified for the
    current request, which is cached for the current thread.

    If ``wagtail.multitenancy.middleware.ActiveTenantMiddleware`` is NOT
    enabled, this function returns the 'default' ``Tenant``.
    """
    from wagtail.models import Tenant

    from .cache import ACTIVE_TENANTS

    current_thread_id = threading.get_ident()
    if current_thread_id not in ACTIVE_TENANTS:
        return Tenant.objects.get_default()
    return ACTIVE_TENANTS[current_thread_id]
