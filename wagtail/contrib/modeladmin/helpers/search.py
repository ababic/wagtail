import operator
from functools import reduce

from django.contrib.admin.utils import lookup_needs_distinct
from django.db.models import Q

from wagtail.search.backends import get_search_backend


class BaseSearchHandler:
    def __init__(self, search_fields):
        self.search_fields = search_fields

    def search_queryset(self, queryset, search_term, **kwargs):
        """
        Returns an iterable of objects from ``queryset`` matching the
        provided ``search_term``.
        """
        raise NotImplementedError()

    @property
    def show_search_form(self):
        """
        Returns a boolean that determines whether a search form should be
        displayed in the IndexView UI.
        """
        return True


class DjangoORMSearchHandler(BaseSearchHandler):
    def search_queryset(self, queryset, search_term, **kwargs):
        if not search_term or not self.search_fields:
            return queryset

        orm_lookups = ['%s__icontains' % str(search_field)
                       for search_field in self.search_fields]
        for bit in search_term.split():
            or_queries = [Q(**{orm_lookup: bit})
                          for orm_lookup in orm_lookups]
            queryset = queryset.filter(reduce(operator.or_, or_queries))
        opts = queryset.model._meta
        for search_spec in orm_lookups:
            if lookup_needs_distinct(opts, search_spec):
                return queryset.distinct()
        return queryset


    @property
    def show_search_form(self):
        return bool(self.search_fields)


class WagtailBackendSearchHandler(BaseSearchHandler):

    default_search_backend = 'default'

    def search_queryset(
        self, queryset, search_term, preserve_order=False, operator=None,
        partial_match=True, backend=None, **kwargs
    ):
        if not search_term:
            return queryset

        backend = get_search_backend(backend or self.default_search_backend)
        return backend.search(
            search_term,
            queryset,
            fields=self.search_fields or None,
            operator=operator,
            partial_match=partial_match,
            order_by_relevance=not preserve_order,
        )


class FilterSimplifyingWagtailBackendSearchHandler(WagtailBackendSearchHandler):
    """
    A search handler that evaluates the supplied queryset, and passes a new
    queryset to the underlying search backend, which is filtered only by the
    model's primary key, but maintains preferences set by annotate(),
    order_by(), select_related() and prefetch_related().
    """

    @staticmethod
    def replace_filters_with_pk_filter(queryset):
        # create new QuerySet
        obj = queryset._clone()
        # nullify any existing filters/exclusions
        obj.query.where = obj.query.where_class()
        # filter the new QuerySet by ids instead
        obj = obj.model._default_manager.filter(pk__in=queryset.values_list('pk', flat=True))
        return obj

    def search_queryset(
        self, queryset, search_term, preserve_order=False, operator=None,
        partial_match=True, backend=None, **kwargs
    ):
        queryset = self.replace_filters_with_pk_filter(queryset)
        return super().search_queryset(queryset, search_term, preserve_order=preserve_order, operator=operator, partial_match=partial_match, backend=backend, **kwargs)
