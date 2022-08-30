from typing import TYPE_CHECKING

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models import Case, Q, When
from django.db.models.functions import Cast
from django.http.request import HttpRequest, split_domain_port
from django.urls import reverse_lazy

from wagtail.multitenancy import cache as tenant_cache
from wagtail.multitenancy import get_default_tenant_id
from wagtail.utils.utils import get_original_pk_field

if TYPE_CHECKING:
    from wagtail.models import Tenant


MATCH_HOSTNAME_PORT = 0
MATCH_HOSTNAME_DEFAULT = 1
MATCH_DEFAULT = 2
MATCH_HOSTNAME = 3

WAGTAIL_ADMIN_PATH = reverse_lazy("wagtailadmin_home")
WAGTAIL_LOGIN_PATH = reverse_lazy("wagtailadmin_login")


class TenantQuerySet(models.QuerySet):
    def open_q(self) -> Q:
        return Q(self.filter)

    def open(self) -> "TenantQuerySet":
        return self.filter(self.open_q())

    def restricted(self) -> "TenantQuerySet":
        return self.exclude(self.open_q())

    def native_to_user_q(self, user) -> Q:
        return Q(id=user.wagtail_userprofile.native_tenant_id)

    def native_to_user(self, user) -> "TenantQuerySet":
        return self.filter(self.native_to_user_q(user))

    def not_native_to_user(self, user) -> "TenantQuerySet":
        return self.exclude(self.native_to_user_q(user))

    def granted_to_user_q(self, user) -> Q:
        return Q(pk__in=user.secondary_tenants.values_list("tenant_id", flat=True))

    def granted_to_user(self, user) -> "TenantQuerySet":
        return self.filter(self.granted_to_user_q(user))

    def not_granted_to_user(self, user) -> "TenantQuerySet":
        return self.exclude(self.granted_to_user_q(user))

    def open_to_user_q(self, user) -> Q:
        return Q(
            self.open_q() | self.native_to_user_q(user) | self.granted_to_user_q(user)
        )

    def open_to_user(self, user) -> "TenantQuerySet":
        return self.filter(self.open_to_user_q(user))

    def closed_to_user(self, user) -> "TenantQuerySet":
        return self.exclude(self.open_to_user_q(user))

    def get_for_request(self, request: HttpRequest) -> "Tenant":
        """
        Return the tenant responsible for handling the supplied ``HttpRequest``.
        """
        cache_attr_name = "_wagtail_tenant"
        if not hasattr(request, cache_attr_name):
            setattr(request, cache_attr_name, self._get_for_request(request))
        return getattr(request, cache_attr_name)

    def _get_for_request(self, request: HttpRequest) -> "Tenant":
        from wagtail.models import Site

        hostname = split_domain_port(request.get_host())[0]
        port = request.get_port()

        # For login requests, use the most appropriate tenant for the
        # hostname/port, to support per-tenant behaviour customisation
        if request.path == str(WAGTAIL_LOGIN_PATH):
            return self.get_for_hostname(hostname, port)

        # For Wagtail admin requests, limit the return value to
        # one the user has access to
        # (there must be a more robust way to figure this out?)
        if request.path.startswith(str(WAGTAIL_ADMIN_PATH)):

            # Abandon lookup here if the user is not authenticated
            # (this request will likely be rejected by the view)
            if not request.user.is_authenticated:
                return

            # If a tenant has been specified via the switcher view, and
            # the user still has access, return the specified tenant
            for_user = self.open_to_user(self, request.user)
            specified_id = request.session.get("wagtail_tenant") or request.COOKIES.get(
                "wagtail_tenant"
            )
            if specified_id:
                for tenant in for_user:
                    if tenant.id == specified_id:
                        return tenant

            try:
                # Find the most suitable match for this user
                return for_user.get_for_hostname(hostname, port)
            except Tenant.DoesNotExist:
                raise ImproperlyConfigured(
                    "No Wagtail tenants are configured to allow access to "
                    f"User '{request.user}', despite them having permission "
                    "to access the Wagtail admin. Did you delete the default "
                    "tenant by mistake? If so, running 'python manage.py "
                    "restore_default_tenant' from the command line may help."
                )

        # For all other requests, assume the request is from a front-end URL,
        # where the hostname should match a Site, rather than a tenant
        try:
            return Site.find_for_request(request).native_tenant
        except Site.DoesNotExist:
            raise self.model.DoesNotExist()

    def get_for_hostname(self, hostname: str, port: int) -> "Tenant":
        default_id = get_default_tenant_id()
        matches = (
            self.annotate(
                match=Case(
                    # annotate the results by best choice descending
                    # put exact hostname+port match first
                    When(hostname=hostname, port=port, then=MATCH_HOSTNAME_PORT),
                    # then put hostname+default (better than just hostname or just default)
                    When(hostname=hostname, id=default_id, then=MATCH_HOSTNAME_DEFAULT),
                    # then match default with different hostname. there is only ever
                    # one default, so order it above (possibly multiple) hostname
                    # matches so we can use sites[0] below to access it
                    When(id=default_id, then=MATCH_DEFAULT),
                    # because of the filter below, if it's not default then its a hostname match
                    default=MATCH_HOSTNAME,
                    output_field=models.IntegerField(),
                )
            )
            .filter(Q(hostname=hostname) | Q(id=default_id))
            .order_by("match")
        )
        if not matches:
            raise self.model.DoesNotExist()

        # if there's a unique match or hostname (with port or default) match
        if len(matches) == 1 or matches[0].match in (
            MATCH_HOSTNAME_PORT,
            MATCH_HOSTNAME_DEFAULT,
        ):
            return matches[0]

        # if there is a default match with a different hostname, see if
        # there are many hostname matches. if only 1 then use that instead
        # otherwise we use the default
        if matches[0].match == MATCH_DEFAULT:
            return matches[len(matches) == 2]

        raise self.model.DoesNotExist()


class TenantManager(models.Manager):
    def get_default(self) -> "Tenant":
        if tenant_cache.DEFAULT_TENANT is None:
            tenant_cache.DEFAULT_TENANT = self.get(id=get_default_tenant_id())
        return tenant_cache.DEFAULT_TENANT


class TenantScopedQuerySet(models.QuerySet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # updated by native_to_active_tenant() and visible_to_active_tenant()
        self._filter_by_active_tenant = False
        self._native_tenant_only = False

    def _clone(self) -> "TenantScopedQuerySet":
        """Ensure clones inherit custom attribute values."""
        clone = super()._clone()
        clone._filter_by_active_tenant = self._filter_by_active_tenant
        clone._native_tenant_only = self._native_tenant_only
        return clone

    def native_to_active_tenant(self) -> "TenantScopedQuerySet":
        """
        Filter the queryset to include items native to the active tenant only.

        NOTE: Filtering is applied 'lazily', at evaluation time.
        """
        clone = self._clone()
        clone._filter_by_active_tenant = True
        clone._native_tenant_only = False
        return clone

    def visible_to_active_tenant(self) -> "TenantScopedQuerySet":
        """
        Filter the queryset to include items native to the active tenant, plus
        any items from other tenants that have been shared with it.

        NOTE: Filtering is applied 'lazily', at evaluation time.
        """
        clone = self._clone()
        clone._filter_by_active_tenant = False
        clone._native_tenant_only = False
        return clone

    def __and__(self, other: "TenantScopedQuerySet") -> "TenantScopedQuerySet":
        """
        When combining two TenantScopedQuerySet objects with the & operator,
        and either of the querysets are to be filtered by the active tenant,
        apply that filtering to the entire combined result.
        """
        combined = super().__and__(other)
        if self._filter_by_active_tenant or other._filter_by_active_tenant:
            combined._filter_by_active_tenant = True
        if self._native_tenant_only or other._native_tenant_only:
            combined._native_tenant_only = True
        return combined

    def __or__(self, other: "TenantScopedQuerySet") -> "TenantScopedQuerySet":
        combined = super().__or__(other)
        if self._filter_by_active_tenant or other._filter_by_active_tenant:
            combined._filter_by_active_tenant = True
        if self._native_tenant_only or other._native_tenant_only:
            combined._native_tenant_only = True
        return combined

    def __iter__(self):
        """
        Overrides QuerySet.__iter__() to apply filtering by the active tenant
        when native_to_active_tenant() or visible_to_active_tenant() have been
        used.
        """
        self._conditionally_apply_active_tenant_filtering()
        return super().__iter__()

    def iterator(self, chunk_size=None):
        """
        Overrides QuerySet.iterator() to apply filtering by the active tenant
        when native_to_active_tenant() or visible_to_active_tenant() have been
        used.
        """
        self._conditionally_apply_active_tenant_filtering()
        if chunk_size is None:
            chunk_size = 2000
        return super().iterator(chunk_size=chunk_size)

    def _conditionally_apply_active_tenant_filtering(self) -> None:
        """
        Used to lazily filter the current queryset in-place to only include
        items native/visible to the active tenant.
        """
        from wagtail.multitenancy import get_active_tenant

        if self._filter_by_active_tenant:
            active_tenant = get_active_tenant()
            if self._native_tenant_only:
                self._filter_or_exclude_inplace(
                    False, (self.native_to_tenant_q(active_tenant),), {}
                )
            else:
                self._filter_or_exclude_inplace(
                    False, (self.visible_to_tenant_q(active_tenant),), {}
                )
            self._filter_by_active_tenant = False

    def native_to_tenant_q(self, tenant: "Tenant") -> Q:
        raise NotImplementedError

    def shared_with_tenant_q(self, tenant: "Tenant") -> Q:
        raise NotImplementedError

    def native_to_tenant(self, tenant: "Tenant") -> "TenantMemberQuerySet":
        return self.filter(self.native_to_tenant_q(tenant))

    def not_native_to_tenant(self, tenant: "Tenant") -> "TenantMemberQuerySet":
        return self.exclude(self.native_to_tenant_q(tenant))

    def shared_with_tenant(self, tenant: "Tenant") -> "TenantMemberQuerySet":
        return self.filter(self.shared_with_tenant_q(tenant))

    def not_shared_with_tenant(self, tenant: "Tenant") -> "TenantMemberQuerySet":
        return self.exclude(self.shared_with_tenant_q(tenant))

    def visible_to_tenant_q(self, tenant: "Tenant") -> Q:
        return Q(self.native_to_tenant_q(tenant) | self.shared_with_tenant_q(tenant))

    def visible_to_tenant(self, tenant: "Tenant") -> "TenantMemberQuerySet":
        return self.filter(self.visible_to_tenant_q(tenant))

    def invisible_to_tenant(self, tenant: "Tenant") -> "TenantMemberQuerySet":
        return self.exclude(self.visible_to_tenant_q(tenant))


class TenantMemberQuerySet(TenantScopedQuerySet):
    def native_to_tenant_q(self, tenant: "Tenant") -> Q:
        return Q(native_tenant=tenant)

    def shared_with_tenant_q(self, tenant: "Tenant") -> Q:
        pk_field = get_original_pk_field(self.model)
        pks_field_name = "object_id"

        # For compatibility with postgres, the 'object_id' values from the
        # link table must be cast to the correct type (int/uuid) for
        # the final 'id__in' filter to work
        subquery = tenant.items_shared_with.filter(
            content_type=ContentType.objects.get_for_model(self.model)
        )
        if isinstance(pk_field, models.IntegerField):
            subquery = subquery.annotate(
                object_id_recast=Cast("object_id", models.IntegerField())
            )
            pks_field_name = "object_id_recast"
        elif issubclass(pk_field, models.UUIDField):
            subquery = subquery.annotate(
                object_id_recast=Cast("object_id", models.UUIDField())
            )
            pks_field_name = "object_id_recast"

        # For compatibility with search, we need to use the actual name of the
        # primary key field instead of 'pk'
        kwargs = {
            f"{pk_field.attname}__in": subquery.values_list(pks_field_name, flat=True)
        }
        return Q(**kwargs)


TenantMemberManager = models.Manager.from_queryset(TenantMemberQuerySet)
