from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet

from wagtail.models import TenantMember
from wagtail.models.collections import CollectionMember
from wagtail.models.sites import SiteMember


def apply_active_tenant_filtering(
    queryset: QuerySet, native_only: bool = True
) -> QuerySet:
    """
    Util function that can be used to apply to 'active tenant' filtering to
    any QuerySet where the model supports it. If not, it fails gracefully,
    leaving the original QuerySet untouched.
    """

    error_fmt = (
        "The queryset for the %(model)s model is missing a %(method_name)s() "
        "method. If you have defined a custom QuerySet or Manager class for "
        "%(model)s, try subclassing the Wagtail's built-in QuerySet or "
        "Manager class for the model, which should include this for you."
    )
    if issubclass(queryset.model, (TenantMember, SiteMember, CollectionMember)):
        if native_only:
            if not hasattr(queryset, "native_to_active_tenant"):
                raise ImproperlyConfigured(
                    error_fmt
                    % {
                        "model": queryset.model,
                        "method_name": "native_to_active_tenant",
                    }
                )
            queryset = queryset.native_to_active_tenant()
        else:
            if not hasattr(queryset, "visible_to_active_tenant"):
                raise ImproperlyConfigured(
                    error_fmt
                    % {
                        "model": queryset.model,
                        "method_name": "visible_to_active_tenant",
                    }
                )
            queryset = queryset.visible_to_active_tenant()
    else:
        # Other models are free to implement their own versions of these filters
        # without subclassing TenantMember, SiteMember or CollectionMember, in
        # which case, they should be used
        if native_only and hasattr(queryset, "native_to_active_tenant"):
            return queryset.native_to_active_tenant()
        if not native_only and hasattr(queryset, "visible_to_active_tenant"):
            return queryset.visible_to_active_tenant()
    return queryset
