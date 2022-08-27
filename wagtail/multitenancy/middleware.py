from threading import current_thread

from django.utils.decorators import sync_only_middleware
from wagtail.models import Tenant
from . import _ACTIVE_TENANTS


@sync_only_middleware
class ActiveTenantMiddleware:
    """
    An optional middleware class for Django projects that make use of multiple
    Wagtail tenants.

    The 'active' ``Tenant`` is identified for the current thread, then cached
    for the duration of the request, allowing
    ``wagtail.tenants.get_active_tenant()`` to return the thread-specific
    value from anywhere, without access to the request, and without hitting
    the database multiple times.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        global _ACTIVE_TENANTS
        thread = current_thread()
        tenant = Tenant.get_for_request(request)
        # Add to global cache, where `wagtail.tenants.get_active_tenant()`
        # can pick it up anywhere within the same thread
        _ACTIVE_TENANTS[thread] = tenant
        try:
            # Continue processing the request
            response = self.get_response(request)
        finally:
            # To prevent memory leaks, always delete the global cache
            # entry before exiting
            del _ACTIVE_TENANTS[thread]
        return response
