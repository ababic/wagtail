import operator
from functools import reduce

from django.contrib.admin.utils import lookup_needs_distinct
from django.db.models import QuerySet, Q

from wagtail.search.backends import get_search_backend
from wagtail.search.backends.base import FilterFieldError


def clear_queryset_ordering(queryset: QuerySet) -> QuerySet:
    obj = queryset._clone()
    obj.query.clear_ordering(True)
    return obj


def clear_queryset_filters(queryset: QuerySet) -> QuerySet:
    obj = queryset._clone()
    obj.query.where = obj.query.where_class()
    return obj


def simplify_queryset_filters(queryset: QuerySet) -> QuerySet:
    """
    Returns an equivalent queryset with any 'where' clauses replaced
    with a single, simple filter which identifies the same rows by
    their primary key, and is far less likely to result in
    ``FilterFieldError`` being raised when passed to the ``search()``
    search method of a Wagtail search backend (provided the pk
    field has been added to the model's ``search_fields`` list using
    ``index.FilterField('field_name')``).

    Requires an additional database query to identify the primary
    key values, which has a clear negative impact on performance.
    """
    # avoid unnecessary work if query isn't filtered
    if not queryset.query.where:
        return queryset
    # return new queryset with filters replaced
    new_queryset = clear_queryset_filters(queryset)
    return new_queryset.filter(pk__in=queryset.values_list('pk', flat=True))


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
        partial_match=True, backend=None, simplify_filters=None, **kwargs
    ):
        if not search_term:
            return queryset

        if not preserve_order:
            # Reduce likelihood of unnecessary OrderByFieldErrors
            queryset = clear_queryset_ordering(queryset)

        backend = get_search_backend(backend or self.default_search_backend)

        try:
            return backend.search(
                search_term,
                queryset,
                fields=self.search_fields or None,
                operator=operator,
                partial_match=partial_match,
                order_by_relevance=not preserve_order,
            )
        except FilterFieldError:
            if simplify_filters is None:
                simplify_filters = self.default_simplify_fitlers
            if simplify_filters:
                return backend.search(
                    search_term,
                    simplify_queryset_filters(queryset),
                    fields=self.search_fields or None,
                    operator=operator,
                    partial_match=partial_match,
                    order_by_relevance=not preserve_order,
                )
            raise
