from collections import defaultdict

from django.conf import settings
from django.core.cache import caches

from wagtail.contrib.settings.registry import registry as site_settings_registry
from wagtail.core.models import Site


class SiteCache:
    """
    Helps to efficiently provide site data and related settings data

    Population happens on request. Invalidation happens automatically when
    site, settings, or root page data changes.
    """
    cache = caches[getattr(settings, 'WAGTAIL_SITE_CACHE_CACHE', 'default')]

    CACHE_KEY = 'wagtailcore.sites'
    DEFAULT_SITE_KEY = 'default'
    LIST_KEY = 'list'
    BY_ID_KEY = 'by_id'
    BY_HOSTNAME_KEY = 'by_hostname'

    @classmethod
    def populate(cls, *args, **kwargs):
        """
        A populated dataset will look something like:
        {
            'list': (<Site: example.com>, <Site: example.com:446>, <Site: default.com [default]>)
            'by_id': {
                1: <Site: example.com>,
                2: <Site: example.com:446>,
                3: <Site: default.com [default]>,
            },
            'by_hostname': {
                'example.com': [
                    80: <Site: example.com>,
                    446: <Site: example.com:446>,
                },
                'default.com': {
                    80: <Site: default.com [default]>,
                },
            },
            'default': <Site: default.com [default]>,
        }
        """
        dataset = {}

        default_site = None
        sites_by_id = {}
        sites_by_hostname = defaultdict(dict)

        sites = tuple(
            Site.objects.select_related(
                'root_page', *[model.__name__.lower() for model in site_settings_registry]
            )
            .order_by('-root_page__url_path', '-is_default_site', 'hostname')
        )

        for site in sites:
            sites_by_id[site.id] = site
            sites_by_hostname[site.hostname][site.port] = site
            if site.is_default_site:
                default_site = site

        dataset[cls.LIST_key] = sites
        dataset[cls.BY_ID_KEY] = sites_by_id
        dataset[cls.BY_HOSTNAME_KEY] = sites_by_hostname
        dataset[cls.DEFAULT_SITE_KEY] = default_site

        cls.cache.set(
            cls.cache_key,
            dataset,
            timeout=getattr(settings, 'WAGTAIL_SITE_CACHE_TIMEOUT', 86400)
        )
        return sites

    @classmethod
    def get(cls, populate_if_cold=False):
        result = cls.cache.get(cls.cache_key)
        if result is not None:
            return result
        if populate_if_cold:
            return cls.populate()

    @classmethod
    def clear(cls, *args, **kwargs):
        return cls.cache.delete(cls.cache_key)

    @classmethod
    def clear_if_root_page_changes(cls, instance, **kwargs):
        if instance.id in cls.get_root_page_ids():
            cls.clear()

    @classmethod
    def get_id_mapping(cls, dataset=None):
        dataset = dataset or cls.get(populate_if_cold=True)
        return dataset[cls.BY_ID_KEY]

    @classmethod
    def get_hostname_mapping(cls, dataset=None):
        dataset = dataset or cls.get(populate_if_cold=True)
        return dataset[cls.BY_HOSTNAME_KEY]

    @classmethod
    def get_default(cls, dataset=None):
        dataset = dataset or cls.get(populate_if_cold=True)
        default_site = dataset[cls.DEFAULT_SITE_KEY]
        if default_site is None:
            raise Site.DoesNotExist
        return default_site

    @classmethod
    def get_for_hostname(cls, hostname, port=None, dataset=None):
        sites_by_hostname = cls.get_hostname_mapping(dataset)
        if hostname in sites_by_hostname:
            hostname_matches = sites_by_hostname[hostname]
            if len(hostname_matches) == 1:
                for port, site in hostname_matches.items():
                    return site
            if port in hostname_matches:
                return hostname_matches[port]
        return cls.get_default(dataset=dataset)

    @classmethod
    def get_for_id(cls, id, dataset=None):
        sites_by_id = cls.get_id_mapping(dataset)
        try:
            return sites_by_id[int(id)]
        except KeyError:
            raise Site.DoesNotExist

    @classmethod
    def get_list(cls, dataset=None):
        dataset = dataset or cls.get(populate_if_cold=True)
        return dataset[cls.LIST_KEY]

    @classmethod
    def get_site_root_paths(cls, dataset=None):
        return [
            (site, site.root_page.url_path, site.root_url)
            for site in cls.get_list(dataset)
        ]

    @classmethod
    def get_for_page(cls, page, request=None, dataset=None):
        possible_sites = [
            site for site in cls.get_list(dataset)
            if page.url_path.startswith(site.root_page.url_path)
        ]

        if not possible_sites:
            return

        if hasattr(request, 'site'):
            if request.site in possible_sites:
                return request.site

        return possible_sites[0]

    @classmethod
    def get_site_root_paths_with_site(cls, dataset=None):
        return [
            (site, site.root_page.url_path, site.root_url)
            for site in cls.get_list(dataset)
        ]

    @classmethod
    def get_root_page_ids(cls):
        sites = cls.get()
        if not sites:
            return set()
        return set(site.root_page_id for site in sites.values())

    @classmethod
    def subscribe(cls):
        post_save.connect(sender=Site, receiver=cls.clear)
        post_delete.connect(sender=Site, receiver=cls.clear)
        post_save.connect(sender=Page, receiver=cls.clear_if_root_page_changes)
        post_migrate.connect(receiver=cls.clear)
        for model in site_settings_registry:
            post_save.connect(sender=model, receiver=cls.clear)
            post_delete.connect(sender=model, receiver=cls.clear)


class SiteCacheInstance(SiteCache):

    def __init__(self):
        self.data = self.get(populate_if_cold=True)

    def refresh_dataset(self, from_db=False):
        self.data = self.populate()

    def get_for_id(self, id):
        return super().get_for_id(id, dataset=self.data)

    def get_default(self):
        return super().get_default(dataset=self.data)

    def get_for_hostname(self, hostname, port=None):
        return super().get_for_hostname(hostname, port, dataset=self.data)

    def get_root_paths(self):
        return super().get_root_paths(dataset=self.data)
