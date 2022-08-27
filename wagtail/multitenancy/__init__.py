from typing import TYPE_CHECKING
from threading import current_thread

from django.http import HttpRequest

if TYPE_CHECKING:
    from wagtail.models import Tenant

# Global cache for per-thread Tenant results, managed by
# ``wagtail.multitenancy.middleware.ActiveTenantMiddleware``
_ACTIVE_TENANTS = {}


def get_active_tenant(request: HttpRequest = None):
    """
    If ``wagtail.multitenancy.middleware.ActiveTenantMiddleware`` is enabled,
    this function returns the ``Tenant`` object already identified for the
    current request, which is cached for the current thread. The supplied
    ``request`` value is completely ignored in this case.

    If ``wagtail.multitenancy.middleware.ActiveTenantMiddleware`` is NOT
    enabled, this function returns the 'default' ``Tenant``. When ``request``
    is supplied, it is used entirely for caching/optimisation. It has no
    bearing on the return value, and is entirely optional.
    """
    from wagtail.models import Tenant

    global _ACTIVE_TENANTS
    thread = current_thread()
    if thread not in _ACTIVE_TENANTS:
        return Tenant.objects.get_default(cache_target=request)
    return _ACTIVE_TENANTS[current_thread()]
