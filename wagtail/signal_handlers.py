import logging

from django.core.cache import cache
from django.db.models.signals import post_delete, post_migrate, post_save, pre_delete

from wagtail.coreutils import get_locales_display_names
from wagtail.models import Locale, Page, Site, Tenant
from wagtail.multitenancy import cache as tenant_cache

logger = logging.getLogger("wagtail")


# Clear the wagtail_site_root_paths from the cache whenever Site records are updated.
def post_save_site_signal_handler(instance, update_fields=None, **kwargs):
    cache.delete("wagtail_site_root_paths")


def post_delete_site_signal_handler(instance, **kwargs):
    cache.delete("wagtail_site_root_paths")


def pre_delete_page_unpublish(sender, instance, **kwargs):
    # Make sure pages are unpublished before deleting
    if instance.live:
        # Don't bother to save, this page is just about to be deleted!
        instance.unpublish(commit=False, log_action=None)


def post_delete_page_log_deletion(sender, instance, **kwargs):
    logger.info('Page deleted: "%s" id=%d', instance.title, instance.id)


def reset_locales_display_names_cache(sender, instance, **kwargs):
    get_locales_display_names.cache_clear()


def refresh_tenant_caches(*args, **kwargs):
    # Fetch fresh batch of tenants
    all_tenants = Tenant.objects.all().in_bulk()
    default_tenant = None
    for tenant in all_tenants.values():
        if tenant.is_default:
            default_tenant = tenant

    # Update DEFAULT_TENANT
    tenant_cache.DEFAULT_TENANT = default_tenant

    # Update ACTIVE_TENANTS
    replacement_value = {}
    for thread_id, tenant in tenant_cache.ACTIVE_TENANTS.items():
        if tenant.id == default_tenant.id:
            replacement_value[thread_id] = default_tenant
        else:
            try:
                # Replace with updated version of tenant
                replacement_value[thread_id] = all_tenants[tenant.id]
            except KeyError:
                # Cached tenant must no longer exist
                replacement_value[thread_id] = default_tenant
    tenant_cache.ACTIVE_TENANTS = replacement_value


def register_signal_handlers():
    post_save.connect(post_save_site_signal_handler, sender=Site)
    post_delete.connect(post_delete_site_signal_handler, sender=Site)

    pre_delete.connect(pre_delete_page_unpublish, sender=Page)
    post_delete.connect(post_delete_page_log_deletion, sender=Page)

    post_save.connect(reset_locales_display_names_cache, sender=Locale)
    post_delete.connect(reset_locales_display_names_cache, sender=Locale)

    post_save.connect(refresh_tenant_caches, sender=Tenant)
    post_delete.connect(refresh_tenant_caches, sender=Tenant)
    post_migrate.connect(refresh_tenant_caches)
