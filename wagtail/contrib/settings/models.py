from django.db import models

from wagtail.core.models import Site

from .registry import register_setting

__all__ = ['BaseSetting', 'register_setting']


class BaseSetting(models.Model):
    """
    The abstract base model for settings. Subclasses must be registered using
    :func:`~wagtail.contrib.settings.registry.register_setting`
    """

    site = models.OneToOneField(
        Site, unique=True, db_index=True, editable=False, on_delete=models.CASCADE)

    class Meta:
        abstract = True

    @classmethod
    def for_site(cls, site):
        """
        Get or create an instance of this setting for the site.
        """
        instance, created = cls.objects.get_or_create(site=site)
        return instance

    @classmethod
    def for_request(cls, request):
        """
        Get or create an instance of this model for the request,
        and cache the result on the request for faster repeat access.
        """
        attr_name = cls.get_cache_attr_name()
        if hasattr(request, attr_name):
            return getattr(request, attr_name)
        site = Site.find_for_request(request)
        site_settings = cls.for_site(site)
        setattr(request, attr_name, site_settings)
        return site_settings

    @classmethod
    def get_cache_attr_name(cls):
        """
        Returns the name of the attribute that should be used to store
        a reference to the fetched/created object on a request.
        """
        return "_{}.{}".format(
            cls._meta.app_label, cls._meta.model_name
        ).lower()
