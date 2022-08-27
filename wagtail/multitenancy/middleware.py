import threading

from django.utils.decorators import sync_only_middleware

from wagtail.models import Tenant


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
        from .cache import ACTIVE_TENANTS

        current_thread_id = threading.get_ident()
        tenant = Tenant.get_for_request(request)

        # Avoid storing more than one version of the default tenant in memory
        if tenant.is_default:
            tenant = Tenant.get_default()

        # Add to global cache, where `wagtail.tenants.get_active_tenant()`
        # can pick it up anywhere within the same thread
        ACTIVE_TENANTS[current_thread_id] = tenant
        try:
            # Continue processing the request
            response = self.get_response(request)
        finally:
            # To prevent memory leaks, always delete the global cache
            # entry before exiting
            del ACTIVE_TENANTS[current_thread_id]
        return response
