from weakref import WeakKeyDictionary

import jinja2
from django.http import HttpRequest
from django.utils.encoding import force_str
from jinja2.ext import Extension

from wagtail.contrib.settings.registry import registry
from wagtail.core.models import Site

# Settings are cached per template context, to prevent excessive database
# lookups. The cached settings are disposed of once the template context is no
# longer used.
settings_cache = WeakKeyDictionary()


class ContextCache(dict):
    """
    A cache of SiteSettingsCache objects keyed by HttpRequest or Site
    """
    def __missing__(self, request_or_site):
        """
        When settings for a new request or site are requested,
        create, cache and return a new SiteSettingsCache
        """
        if not(isinstance(request_or_site, (HttpRequest, Site))):
            raise TypeError
        self[request_or_site] = obj = SiteSettingsCache(request_or_site)
        return obj


class SiteSettingsCache(dict):
    """
    A cache of Settings objects for a specific HttpRequest or Site,
    keyed by 'app_label.Model' style strings.
    """
    def __init__(self, request_or_site):
        super().__init__()
        self.request_or_site = request_or_site

    def __getitem__(self, key):
        # Normalise all keys to lowercase
        return super().__getitem__(force_str(key).lower())

    def __missing__(self, key):
        """
        When new settings are requested for a request or site,
        fetch, cache and return the relevant object.
        """
        try:
            app_label, model_name = key.split('.', 1)
        except ValueError:
            raise KeyError('Invalid model name: {}'.format(key))
        Model = registry.get_by_natural_key(app_label, model_name)
        if Model is None:
            raise KeyError('Unknown setting: {}'.format(key))

        if isinstance(self.request_or_site, Site):
            obj = Model.for_site(self.request_or_site)
        else:
            obj = Model.for_request(self.request_or_site)
        self[key] = obj
        return obj


@jinja2.contextfunction
def get_setting(context, model_string, use_default_site=False):
    if use_default_site:
        request_or_site = Site.objects.get(is_default_site=True)
    elif 'request' in context:
        request_or_site = context['request']
    else:
        raise RuntimeError('No request found in context, and use_default_site '
                           'flag not set')

    # WeakKeyDictionary does not support __missing__, so we create
    # a ContextCache below if one does not already exist
    try:
        context_cache = settings_cache[context]
    except KeyError:
        context_cache = settings_cache[context] = ContextCache()
    return context_cache[request_or_site][model_string]


class SettingsExtension(Extension):
    def __init__(self, environment):
        super().__init__(environment)
        self.environment.globals.update({
            'settings': get_setting,
        })


settings = SettingsExtension
