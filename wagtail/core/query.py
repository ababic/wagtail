import posixpath
import warnings

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import CharField, Q
from django.db.models.functions import Length, Substr
from django.db.models.query import ModelIterable
from treebeard.mp_tree import MP_NodeQuerySet

from wagtail.search.queryset import SearchableQuerySetMixin


SPECIFIC_CLASS_UNAVAILABLE_CODE = 'SPECIFIC_CLASS_UNAVAILABLE'
SPECIFIC_DATA_UNAVAILABLE_CODE = 'SPECIFIC_DATA_UNAVAILABLE'


class PageUpcastErrorsWarning(RuntimeWarning):
    pass


class PageUpcastError:
    """
    Represents an error that occured while upcasting a page to its most
    specific type during evaluation of a ``PageQuerySet``.
    """
    __slots__ = ['page_id', 'url_path', 'content_type', 'code']

    def __init__(self, page_id: int, url_path: str, content_type: ContentType, code: str) -> None:
        self.page_id = page_id
        self.url_path = url_path
        self.content_type = content_type
        self.code = code


class PageUpcastErrorList:
    """
    Represents a series of ``UpcastError`` that occured while upcasting
    pages to their most specific type.
    """
    __slots__ = ["queryset", "errors"]

    def __init__(self, queryset: 'PageQuerySet'):
        self.queryset = queryset
        self.errors = []

    def __iter__(self):
        return iter(self.errors)

    def __bool__(self):
        return bool(self.errors)

    def __str__(self) -> str:
        if not self.errors:
            return '[]'
        return (
            f"A recently evaluated {self.queryset.__class__} could "
            f"only return generic {self.queryset.model} instances "
            f"for some items, because of the following errors:\n{self.errors}"
        )

    def add(self, page, code: str) -> None:
        """
        Log an upcast error for ``page`` (a ``Page`` instance) with the
        provided ``code``.
        """
        self.errors.append(
            PageUpcastError(page_id=page.id, url_path=page.url_path, content_type=page.cached_content_type, code=code)
        )

    def warn(self, stacklevel: int = 1) -> None:
        """
        If upcast errors have been added, generate a warning.
        """
        if self.errors:
            warnings.warn(str(self), category=PageUpcastErrorsWarning, stacklevel=stacklevel)


class TreeQuerySet(MP_NodeQuerySet):
    """
    Extends Treebeard's MP_NodeQuerySet with additional useful tree-related operations.
    """
    def delete(self):
        """Redefine the delete method unbound, so we can set the queryset_only parameter. """
        super().delete()

    delete.queryset_only = True

    def descendant_of_q(self, other, inclusive=False):
        q = Q(path__startswith=other.path) & Q(depth__gte=other.depth)

        if not inclusive:
            q &= ~Q(pk=other.pk)

        return q

    def descendant_of(self, other, inclusive=False):
        """
        This filters the QuerySet to only contain pages that descend from the specified page.

        If inclusive is set to True, it will also contain the page itself (instead of just its descendants).
        """
        return self.filter(self.descendant_of_q(other, inclusive))

    def not_descendant_of(self, other, inclusive=False):
        """
        This filters the QuerySet to not contain any pages that descend from the specified page.

        If inclusive is set to True, it will also exclude the specified page.
        """
        return self.exclude(self.descendant_of_q(other, inclusive))

    def child_of_q(self, other):
        return self.descendant_of_q(other) & Q(depth=other.depth + 1)

    def child_of(self, other):
        """
        This filters the QuerySet to only contain pages that are direct children of the specified page.
        """
        return self.filter(self.child_of_q(other))

    def not_child_of(self, other):
        """
        This filters the QuerySet to not contain any pages that are direct children of the specified page.
        """
        return self.exclude(self.child_of_q(other))

    def ancestor_of_q(self, other, inclusive=False):
        paths = [
            other.path[0:pos]
            for pos in range(0, len(other.path) + 1, other.steplen)[1:]
        ]
        q = Q(path__in=paths)

        if not inclusive:
            q &= ~Q(pk=other.pk)

        return q

    def ancestor_of(self, other, inclusive=False):
        """
        This filters the QuerySet to only contain pages that are ancestors of the specified page.

        If inclusive is set to True, it will also include the specified page.
        """
        return self.filter(self.ancestor_of_q(other, inclusive))

    def not_ancestor_of(self, other, inclusive=False):
        """
        This filters the QuerySet to not contain any pages that are ancestors of the specified page.

        If inclusive is set to True, it will also exclude the specified page.
        """
        return self.exclude(self.ancestor_of_q(other, inclusive))

    def parent_of_q(self, other):
        return Q(path=self.model._get_parent_path_from_path(other.path))

    def parent_of(self, other):
        """
        This filters the QuerySet to only contain the parent of the specified page.
        """
        return self.filter(self.parent_of_q(other))

    def not_parent_of(self, other):
        """
        This filters the QuerySet to exclude the parent of the specified page.
        """
        return self.exclude(self.parent_of_q(other))

    def sibling_of_q(self, other, inclusive=True):
        q = Q(path__startswith=self.model._get_parent_path_from_path(other.path)) & Q(depth=other.depth)

        if not inclusive:
            q &= ~Q(pk=other.pk)

        return q

    def sibling_of(self, other, inclusive=True):
        """
        This filters the QuerySet to only contain pages that are siblings of the specified page.

        By default, inclusive is set to True so it will include the specified page in the results.

        If inclusive is set to False, the page will be excluded from the results.
        """
        return self.filter(self.sibling_of_q(other, inclusive))

    def not_sibling_of(self, other, inclusive=True):
        """
        This filters the QuerySet to not contain any pages that are siblings of the specified page.

        By default, inclusive is set to True so it will exclude the specified page from the results.

        If inclusive is set to False, the page will be included in the results.
        """
        return self.exclude(self.sibling_of_q(other, inclusive))


class PageQuerySet(SearchableQuerySetMixin, TreeQuerySet):
    def __init__(self, *args, **kwargs):
        """Set custom instance attributes"""
        super().__init__(*args, **kwargs)
        self.upcast_errors = PageUpcastErrorList(self)
        # custom iterable to conditionally apply upcasting
        self._iterable_class = PageIterable
        # PageIterable utilizes the following values:
        # updated by specific() and generic()
        self._yield_specific_instances = False
        self._defer_specific_fields = False
        # updated by defer_streamfields()
        self._defer_streamfields = False
        # updated by type(), exact_type() or page()
        self._types_requested = set()
        # updated by not_type() or not_exact_type()
        self._types_excluded = set()

    def _clone(self):
        """Ensure clones inherit custom attribute values."""
        clone = super()._clone()
        clone._yield_specific_instances = self._yield_specific_instances
        clone._defer_specific_fields = self._defer_specific_fields
        clone._defer_streamfields = self._defer_streamfields
        # these sets must be recreated in order to avoid
        # unintended cross-queryset contamination
        clone._types_requested = self._types_requested.copy()
        clone._types_excluded = self._types_excluded.copy()
        return clone

    def __and__(self, other: 'PageQuerySet'):
        combined = super().__and__(other)
        combined._yield_specific_instances = self._yield_specific_instances or other._yield_specific_instances
        combined._defer_specific_fields = self._defer_specific_fields or other._defer_specific_fields
        combined._defer_streamfields = self._defer_streamfields or other._defer_streamfields
        combined._types_requested = self._types_requested & other._types_requested
        combined._types_excluded = self._types_excluded & other._types_excluded
        return combined

    def __or__(self, other: 'PageQuerySet'):
        combined = super().__or__(other)
        combined._yield_specific_instances = self._yield_specific_instances or other._yield_specific_instances
        combined._defer_specific_fields = self._defer_specific_fields or other._defer_specific_fields
        combined._defer_streamfields = self._defer_streamfields or other._defer_streamfields
        combined._types_requested = self._types_requested | other._types_requested
        combined._types_excluded = self._types_excluded | other._types_excluded
        return combined

    def log_upcast_error(self, obj, code: str):
        self.upcast_errors.add(obj, code)

    def _fetch_all(self):
        """
        Overrides QuerySet._fetch_all() to warn about upcast errors on
        evaluation.
        """
        super()._fetch_all()
        self.upcast_errors.warn(stacklevel=3)

    def live_q(self):
        return Q(live=True)

    def live(self):
        """
        This filters the QuerySet to only contain published pages.
        """
        return self.filter(self.live_q())

    def not_live(self):
        """
        This filters the QuerySet to only contain unpublished pages.
        """
        return self.exclude(self.live_q())

    def in_menu_q(self):
        return Q(show_in_menus=True)

    def in_menu(self):
        """
        This filters the QuerySet to only contain pages that are in the menus.
        """
        return self.filter(self.in_menu_q())

    def not_in_menu(self):
        """
        This filters the QuerySet to only contain pages that are not in the menus.
        """
        return self.exclude(self.in_menu_q())

    def page_q(self, other):
        return Q(id=other.id)

    def page(self, other):
        """
        This filters the QuerySet so it only contains the specified page.
        """
        self._types_requested = {other.specific_class}
        return self.filter(self.page_q(other))

    def not_page(self, other):
        """
        This filters the QuerySet so it doesn't contain the specified page.
        """
        return self.exclude(self.page_q(other))

    def type_q(self, *types, excluding=False):
        all_subclasses = set(
            model for model in apps.get_models()
            if issubclass(model, types)
        )
        if excluding:
            self._types_excluded.update(all_subclasses)
        else:
            self._types_requested = all_subclasses
        content_types = ContentType.objects.get_for_models(*all_subclasses)
        return Q(content_type__in=list(content_types.values()))

    def type(self, *types):
        """
        This filters the QuerySet to only contain pages that are an instance
        of the specified model(s) (including subclasses).
        """
        return self.filter(self.type_q(*types))

    def not_type(self, *types):
        """
        This filters the QuerySet to exclude any pages which are an instance of the specified model(s).
        """
        return self.exclude(self.type_q(*types, excluding=True))

    def exact_type_q(self, *types, excluding=False):
        if excluding:
            self._types_excluded.update(types)
        else:
            self._types_requested = set(types)
        content_types = ContentType.objects.get_for_models(*types)
        return Q(content_type__in=list(content_types.values()))

    def exact_type(self, *types):
        """
        This filters the QuerySet to only contain pages that are an instance of the specified model(s)
        (matching the model exactly, not subclasses).
        """
        return self.filter(self.exact_type_q(*types))

    def not_exact_type(self, *types):
        """
        This filters the QuerySet to exclude any pages which are an instance of the specified model(s)
        (matching the model exactly, not subclasses).
        """
        return self.exclude(self.exact_type_q(*types, excluding=True))

    def public_q(self):
        from wagtail.core.models import PageViewRestriction

        q = Q()
        for restriction in PageViewRestriction.objects.select_related('page').all():
            q &= ~self.descendant_of_q(restriction.page, inclusive=True)
        return q

    def public(self):
        """
        This filters the QuerySet to only contain pages that are not in a private section
        """
        return self.filter(self.public_q())

    def not_public(self):
        """
        This filters the QuerySet to only contain pages that are in a private section
        """
        return self.exclude(self.public_q())

    def first_common_ancestor(self, include_self=False, strict=False):
        """
        Find the first ancestor that all pages in this queryset have in common.
        For example, consider a page hierarchy like::

            - Home/
                - Foo Event Index/
                    - Foo Event Page 1/
                    - Foo Event Page 2/
                - Bar Event Index/
                    - Bar Event Page 1/
                    - Bar Event Page 2/

        The common ancestors for some queries would be:

        .. code-block:: python

            >>> Page.objects\\
            ...     .type(EventPage)\\
            ...     .first_common_ancestor()
            <Page: Home>
            >>> Page.objects\\
            ...     .type(EventPage)\\
            ...     .filter(title__contains='Foo')\\
            ...     .first_common_ancestor()
            <Page: Foo Event Index>

        This method tries to be efficient, but if you have millions of pages
        scattered across your page tree, it will be slow.

        If `include_self` is True, the ancestor can be one of the pages in the
        queryset:

        .. code-block:: python

            >>> Page.objects\\
            ...     .filter(title__contains='Foo')\\
            ...     .first_common_ancestor()
            <Page: Foo Event Index>
            >>> Page.objects\\
            ...     .filter(title__exact='Bar Event Index')\\
            ...     .first_common_ancestor()
            <Page: Bar Event Index>

        A few invalid cases exist: when the queryset is empty, when the root
        Page is in the queryset and ``include_self`` is False, and when there
        are multiple page trees with no common root (a case Wagtail does not
        support). If ``strict`` is False (the default), then the first root
        node is returned in these cases. If ``strict`` is True, then a
        ``ObjectDoesNotExist`` is raised.
        """
        # An empty queryset has no ancestors. This is a problem
        if not self.exists():
            if strict:
                raise self.model.DoesNotExist('Can not find ancestor of empty queryset')
            return self.model.get_first_root_node()

        if include_self:
            # Get all the paths of the matched pages.
            paths = self.order_by().values_list('path', flat=True)
        else:
            # Find all the distinct parent paths of all matched pages.
            # The empty `.order_by()` ensures that `Page.path` is not also
            # selected to order the results, which makes `.distinct()` works.
            paths = self.order_by()\
                .annotate(parent_path=Substr(
                    'path', 1, Length('path') - self.model.steplen,
                    output_field=CharField(max_length=255)))\
                .values_list('parent_path', flat=True)\
                .distinct()

        # This method works on anything, not just file system paths.
        common_parent_path = posixpath.commonprefix(paths)

        # That may have returned a path like (0001, 0002, 000), which is
        # missing some chars off the end. Fix this by trimming the path to a
        # multiple of `Page.steplen`
        extra_chars = len(common_parent_path) % self.model.steplen
        if extra_chars != 0:
            common_parent_path = common_parent_path[:-extra_chars]

        if common_parent_path == '':
            # This should only happen when there are multiple trees,
            # a situation that Wagtail does not support;
            # or when the root node itself is part of the queryset.
            if strict:
                raise self.model.DoesNotExist('No common ancestor found!')

            # Assuming the situation is the latter, just return the root node.
            # The root node is not its own ancestor, so this is technically
            # incorrect. If you want very correct operation, use `strict=True`
            # and receive an error.
            return self.model.get_first_root_node()

        # Assuming the database is in a consistent state, this page should
        # *always* exist. If your database is not in a consistent state, you've
        # got bigger problems.
        return self.model.objects.get(path=common_parent_path)

    def unpublish(self):
        """
        This unpublishes all live pages in the QuerySet.
        """
        for page in self.live():
            page.unpublish()

    def defer_streamfields(self):
        """
        Apply to a queryset to prevent fetching/decoding of StreamField values on
        evaluation. Useful when working with potentially large numbers of results,
        where StreamField values are unlikely to be needed. For example, when
        generating a sitemap or a long list of page links.
        """
        clone = self._clone()
        clone._defer_streamfields = True  # used by specific_iterator()
        streamfield_names = self.model.get_streamfield_names()
        if not streamfield_names:
            return clone
        return clone.defer(*streamfield_names)

    def specific(self, defer=False):
        """
        This efficiently gets all the specific pages for the queryset, using
        the minimum number of queries.

        When the "defer" keyword argument is set to True, only generic page
        field values will be loaded and all specific fields will be deferred.
        """
        clone = self._clone()
        clone._yield_specific_instances = True
        if defer:
            clone._defer_specific_fields = True
        else:
            clone._defer_specific_fields = False
        return clone

    def in_site(self, site):
        """
        This filters the QuerySet to only contain pages within the specified site.
        """
        return self.descendant_of(site.root_page, inclusive=True)

    def translation_of_q(self, page, inclusive):
        q = Q(translation_key=page.translation_key)

        if not inclusive:
            q &= ~Q(pk=page.pk)

        return q

    def translation_of(self, page, inclusive=False):
        """
        This filters the QuerySet to only contain pages that are translations of the specified page.

        If inclusive is True, the page itself is returned.
        """
        return self.filter(self.translation_of_q(page, inclusive))

    def not_translation_of(self, page, inclusive=False):
        """
        This filters the QuerySet to only contain pages that are not translations of the specified page.

        Note, this will include the page itself as the page is technically not a translation of itself.
        If inclusive is True, we consider the page to be a translation of itself so this excludes the page
        from the results.
        """
        return self.exclude(self.translation_of_q(page, inclusive))


class PageIterable(ModelIterable):
    """
    A custom iterable class used by ``PageQuerySet`` to support on-the-fly
    upcasting of generic ``Page`` instances to their 'most specific' type.
    """
    def __iter__(self):
        if not self.queryset._yield_specific_instances:
            iterable = super()
        if self.queryset._defer_specific_fields:
            iterable = DeferredSpecificIterable(self.queryset)
        else:
            iterable = SpecificIterable(self.queryset)
        yield from iterable


class SpecificIterable(ModelIterable):
    def __iter__(self):
        specific_lookups = self.get_specific_lookups()

        # Avoid additional work if there is no upgrading to be done
        if not specific_lookups:
            return super().__iter__()

        self.apply_specific_lookups(specific_lookups)

        if self.queryset._defer_streamfields:
            self.defer_specific_streamfields(specific_lookups)

        content_types = ContentType.objects.get_for_models(*specific_lookups.keys())
        ctypeid_to_model = {
            ctype.id: model for model, ctype in content_types.items()
        }

        for obj in super().__iter__():
            target_model = ctypeid_to_model.get(obj.content_type_id)
            if target_model is None:
                yield obj
                continue

            related_name = specific_lookups.get(target_model)
            if related_name:
                yield self.upgrade_instance(obj, related_name)
            else:
                self.queryset.upcast_errors.add(obj, code=SPECIFIC_CLASS_UNAVAILABLE_CODE)
                yield obj

    def get_specific_lookups(self):
        """
        Return a dictionary of concrete subclasses that might appear in the
        queryset result, along with the strings that can be used by
        'select_related' to include the data for that model in the result.
        """
        generic_type = self.queryset.model
        all_type_info = generic_type.get_concrete_subclasses()

        requested_types = self.queryset._types_requested
        excluded_types = self.queryset._types_excluded

        if not requested_types and not excluded_types:
            return all_type_info

        if requested_types:
            types_of_interest = requested_types
        else:
            types_of_interest = set(all_type_info.keys())
        return {
            k: v for k, v in all_type_info.items() if k in types_of_interest and k not in excluded_types
        }

    def apply_specific_lookups(self, specific_lookups):
        # Use select_related() to fetch subclass model data
        # while retaining existing 'select_related' values
        previous_select_related = self.queryset.query.select_related
        queryset = self.queryset.select_related(*specific_lookups.values())
        if isinstance(previous_select_related, dict):
            queryset.query.select_related.update(previous_select_related)
        self.queryset = queryset

    def defer_specific_streamfields(self, specific_lookups):
        if not self.queryset._defer_streamfields:
            return

        # Gather streamfield names from subclasses
        field_names = []
        for model, related_name in specific_lookups.items():
            field_names.extend(model.get_streamfield_names(prefix=related_name))
        if field_names:
            # defer collected streamfield names
            self.queryset = self.queryset.defer(*field_names)

    def upgrade_instance(self, obj, rel_name):
        """
        Upgrade a Page object to its most specific type, copying prefetched
        data and any other attribute values.
        """
        if not rel_name:
            return obj

        new_obj = obj
        for rel in rel_name.split("__"):
            try:
                new_obj = getattr(new_obj, rel)
            except (ObjectDoesNotExist, AttributeError):
                self.queryset.log_upcast_error(obj, code=SPECIFIC_DATA_UNAVAILABLE_CODE)
                return new_obj

        # copy prefetches
        if hasattr(obj, "_prefetched_objects_cache"):
            if not hasattr(new_obj, "_prefetched_objects_cache"):
                new_obj._prefetched_objects_cache = {}
            new_obj._prefetched_objects_cache.update(obj._prefetched_objects_cache)

        # copy all other attributes values
        for k, v in (
            (k, v) for k, v in obj.__dict__.items() if k not in new_obj.__dict__
        ):
            setattr(new_obj, k, v)

        return new_obj


class DeferredSpecificIterable(ModelIterable):
    def __iter__(self):
        for obj in super().__iter__():
            if obj.specific_class:
                yield obj.specific_deferred
            else:
                self.queryset.log_upcast_error(obj, code=SPECIFIC_CLASS_UNAVAILABLE_CODE)
                yield obj
