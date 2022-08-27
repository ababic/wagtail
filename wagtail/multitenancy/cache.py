from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from wagtail.models import Tenant

# Global cache for per-thread Tenant results, managed by
# ``wagtail.multitenancy.middleware.ActiveTenantMiddleware``
ACTIVE_TENANTS: Dict[int, "Tenant"] = {}

# Global cache for default Tenant, managed by signals
DEFAULT_TENANT: "Tenant" = None
