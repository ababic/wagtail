from collections.abc import Mapping

from django.db.models.base import ModelBase
from django.db.models.fields import Field


def deep_update(source, overrides):
    """Update a nested dictionary or similar mapping.

    Modify ``source`` in place.
    """
    for key, value in overrides.items():
        if isinstance(value, Mapping) and value:
            returned = deep_update(source.get(key, {}), value)
            source[key] = returned
        else:
            source[key] = overrides[key]
    return source


def get_original_pk_field(model: ModelBase) -> Field:
    """
    Return the original 'primary key' field for the supplied model.

    With concrete multi-table-inheritance chains, we want traverse
    automatically added `_ptr` fields until we get to the 'pk' field
    on the last ancestor model in the chain (e.g. `Page.id`).

    We also want to traverse manually added `OneToOneField`s to access
    access the `pk` field from the target model, then continue
    though that chain until we have the model's original 'pk' field.
    """
    field = model._meta.pk
    try:
        return get_original_pk_field(field.related_model)
    except AttributeError:
        return field
