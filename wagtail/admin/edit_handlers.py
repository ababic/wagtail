import functools
import re
import types
from itertools import chain

from django import forms
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.db.models.fields import CharField, Field, TextField, reverse_related
from django.forms.formsets import DELETION_FIELD_NAME, ORDERING_FIELD_NAME
from django.forms.models import fields_for_model
from django.forms.widgets import Widget
from django.template.loader import render_to_string
from django.utils.functional import cached_property
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy
from taggit.managers import TaggableManager

from wagtail.admin import compare, widgets
from wagtail.core.fields import RichTextField, StreamField
from wagtail.core.models import Page
from wagtail.core.utils import accepts_kwarg, camelcase_to_underscore, resolve_model_string

from modelcluster.fields import ParentalKey

# DIRECT_FORM_FIELD_OVERRIDES, FORM_FIELD_OVERRIDES are imported for backwards
# compatibility, as people are likely importing them from here and then
# appending their own overrides
from .forms.models import (  # NOQA
    DIRECT_FORM_FIELD_OVERRIDES, FORM_FIELD_OVERRIDES, WagtailAdminModelForm, formfield_for_dbfield)
from .forms.pages import WagtailAdminPageForm


def widget_with_script(widget, script):
    return mark_safe('{0}<script>{1}</script>'.format(widget, script))


def get_form_for_model(
    model, form_class=WagtailAdminModelForm,
    fields=None, exclude=None, formsets=None, exclude_formsets=None, widgets=None
):

    # django's modelform_factory with a bit of custom behaviour
    attrs = {'model': model}
    if fields is not None:
        attrs['fields'] = fields
    if exclude is not None:
        attrs['exclude'] = exclude
    if widgets is not None:
        attrs['widgets'] = widgets
    if formsets is not None:
        attrs['formsets'] = formsets
    if exclude_formsets is not None:
        attrs['exclude_formsets'] = exclude_formsets

    # Give this new form class a reasonable name.
    class_name = model.__name__ + str('Form')
    bases = (object,)
    if hasattr(form_class, 'Meta'):
        bases = (form_class.Meta,) + bases

    form_class_attrs = {
        'Meta': type(str('Meta'), bases, attrs)
    }

    metaclass = type(form_class)
    return metaclass(class_name, (form_class,), form_class_attrs)


def get_editable_field_names_for_model(model, exclude=()):
    opts = model._meta
    sortable_private_fields = [f for f in opts.private_fields if isinstance(f, Field)]
    for field in sorted(chain(opts.concrete_fields, sortable_private_fields, opts.many_to_many)):
        if getattr(field, 'editable', True) and field.name not in exclude:
            yield field.name


def get_model_field_or_attribute(model, attr_name):
    try:
        return model._meta.get_field(attr_name)
    except FieldDoesNotExist:
        instance = model()
        if hasattr(instance, attr_name):
            return getattr(instance, attr_name)
        raise AttributeError(
            f"{model.__name__} instances have no field or attribute "
            f"matching the name '{attr_name}'."
        )


def extract_panel_definitions_from_model_class(model, exclude=None):
    if hasattr(model, 'panels'):
        return model.panels

    panels = []

    _exclude = []
    if exclude:
        _exclude.extend(exclude)

    fields = fields_for_model(model, exclude=_exclude, formfield_callback=formfield_for_dbfield)

    for field_name, field in fields.items():
        try:
            panel_class = field.widget.get_panel()
        except AttributeError:
            panel_class = FieldPanel

        panel = panel_class(field_name)
        panels.append(panel)

    return panels


def get_edit_handler(model, instance=None, request=None):
    if hasattr(model, "edit_handler"):
        return model.edit_handler

    if hasattr(model, "get_edit_handler"):
        method = model.get_edit_handler
        kwargs = {}
        if accepts_kwarg(method, "instance"):
            kwargs["instance"] = instance
        if accepts_kwarg(method, "request"):
            kwargs["request"] = request
        return method(**kwargs)

    if hasattr(model, "tab_definitions"):
        return TabbedInterface(children=model.tab_definitions)

    return ObjectList(children=getattr(model, "panels", None))


def get_panel_class(attr_name, model_attr):
    from wagtail.documents.models import AbstractDocument
    from wagtail.documents.edit_handlers import DocumentChooserPanel
    from wagtail.images.models import AbstractImage
    from wagtail.images.edit_handlers import ImageChooserPanel
    from wagtail.snippets.models import get_snippet_models
    from wagtail.snippets.edit_handlers import SnippetChooserPanel

    if isinstance(model_attr, StreamField):
        return StreamFieldPanel
    if isinstance(model_attr, RichTextField):
        return RichTextFieldPanel
    if isinstance(model_attr, models.ForeignKey):
        target_model = model_attr.related_model
        if issubclass(target_model, Page):
            return PageChooserPanel
        if issubclass(target_model, AbstractImage):
            return ImageChooserPanel
        if issubclass(target_model, AbstractDocument):
            return DocumentChooserPanel
        if target_model in get_snippet_models():
            return SnippetChooserPanel
    if not isinstance(model_attr, models.fields.Field):
        return ReadOnlyPanel
    return FieldPanel


class EditHandler:
    """
    Abstract class providing sensible default behaviours for objects implementing
    the EditHandler API
    """
    tab_class = None
    multifield_panel_class = None
    row_panel_class = None
    inline_panel_class = None
    default_field_panel_class = None
    default_non_field_panel_class = None

    def __init__(self, heading="", classname="", help_text=""):
        self.heading = heading
        self.classname = classname
        self.help_text = help_text
        self.model = None
        self.instance = None
        self.request = None
        self.form = None

    def clone(self):
        return self.__class__(**self.clone_kwargs())

    def clone_kwargs(self):
        return {
            'heading': self.heading,
            'classname': self.classname,
            'help_text': self.help_text,
        }

    # return list of widget overrides that this EditHandler wants to be in place
    # on the form it receives
    def widget_overrides(self):
        return {}

    # return list of fields that this EditHandler expects to find on the form
    def required_fields(self):
        return []

    # return a dict of formsets that this EditHandler requires to be present
    # as children of the ClusterForm; the dict is a mapping from relation name
    # to parameters to be passed as part of get_form_for_model's 'formsets' kwarg
    def required_formsets(self):
        return {}

    # return any HTML that needs to be output on the edit page once per edit handler definition.
    # Typically this will be used to define snippets of HTML within <script type="text/x-template"></script> blocks
    # for Javascript code to work with.
    def html_declarations(self):
        return ''

    def bind_to(self, model=None, instance=None, request=None, form=None):
        if model is None and instance is not None and self.model is None:
            model = instance._meta.model

        new = self.clone()
        new.model = self.model if model is None else model
        new.instance = self.instance if instance is None else instance
        new.request = self.request if request is None else request
        new.form = self.form if form is None else form

        if new.model is not None:
            new.on_model_bound()

        if new.instance is not None:
            new.on_instance_bound()

        if new.request is not None:
            new.on_request_bound()

        if new.form is not None:
            new.on_form_bound()

        return new

    def on_model_bound(self):
        pass

    def on_instance_bound(self):
        pass

    def on_request_bound(self):
        pass

    def on_form_bound(self):
        pass

    def __repr__(self):
        return '<%s with model=%s instance=%s request=%s form=%s>' % (
            self.__class__.__name__,
            self.model, self.instance, self.request, self.form.__class__.__name__)

    def classes(self):
        """
        Additional CSS classnames to add to whatever kind of object this is at output.
        Subclasses of EditHandler should override this, invoking super().classes() to
        append more classes specific to the situation.
        """
        if self.classname:
            return [self.classname]
        return []

    def field_type(self):
        """
        The kind of field it is e.g boolean_field. Useful for better semantic markup of field display based on type
        """
        return ""

    def id_for_label(self):
        """
        The ID to be used as the 'for' attribute of any <label> elements that refer
        to this object but are rendered outside of it. Leave blank if this object does not render
        as a single input field.
        """
        return ""

    def render_as_object(self):
        """
        Render this object as it should appear within an ObjectList. Should not
        include the <h2> heading or help text - ObjectList will supply those
        """
        # by default, assume that the subclass provides a catch-all render() method
        return self.render()

    def render_as_field(self):
        """
        Render this object as it should appear within a <ul class="fields"> list item
        """
        # by default, assume that the subclass provides a catch-all render() method
        return self.render()

    def render_missing_fields(self):
        """
        Helper function: render all of the fields that are defined on the form but not "claimed" by
        any panels via required_fields. These fields are most likely to be hidden fields introduced
        by the forms framework itself, such as ORDER / DELETE fields on formset members.

        (If they aren't actually hidden fields, then they will appear as ugly unstyled / label-less fields
        outside of the panel furniture. But there's not much we can do about that.)
        """
        rendered_fields = self.required_fields()
        missing_fields_html = [
            str(self.form[field_name])
            for field_name in self.form.fields
            if field_name not in rendered_fields
        ]

        return mark_safe(''.join(missing_fields_html))

    def render_form_content(self):
        """
        Render this as an 'object', ensuring that all fields necessary for a valid form
        submission are included
        """
        return mark_safe(self.render_as_object() + self.render_missing_fields())

    def get_comparison(self):
        return []


class BaseCompositeEditHandler(EditHandler):
    """
    Abstract class for EditHandlers that manage a set of sub-EditHandlers.
    Concrete subclasses must attach a 'children' property
    """
    panels = None

    def __init__(self, children=(), exclude_fields=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.children = children
        self.exclude_fields = exclude_fields or ()

    def clone_kwargs(self):
        kwargs = super().clone_kwargs()
        kwargs["children"] = self.children
        return kwargs

    def widget_overrides(self):
        # build a collated version of all its children's widget lists
        widgets = {}
        for handler_class in self.children:
            widgets.update(handler_class.widget_overrides())
        widget_overrides = widgets

        return widget_overrides

    def required_fields(self):
        fields = []
        for handler in self.children:
            fields.extend(handler.required_fields())
        return fields

    def required_formsets(self):
        formsets = {}
        for handler_class in self.children:
            formsets.update(handler_class.required_formsets())
        return formsets

    def html_declarations(self):
        return mark_safe("".join([c.html_declarations() for c in self.children]))

    @staticmethod
    def get_panel_class(name, model_field_or_attr):
        return get_panel_class(name, model_field_or_attr)

    def create_panel(self, definition, **kwargs):
        if isinstance(definition, tuple) and len(definition) == 1:
            # unpack single-item tuples
            definition = definition[0]

        if isinstance(definition, str):
            return self.create_panel_from_string(definition, **kwargs)

        if isinstance(definition, tuple):
            return self.create_panel_from_tuple(definition, **kwargs)

        if isinstance(definition, dict):
            return self.create_panel_from_dict(definition, **kwargs)

        if isinstance(definition, EditHandler):
            return definition

    def create_panel_from_string(self, value, **kwargs):
        """
        Return a panel instance to represent the provided string value - which
        should be a model field name or an attribute of the instance or model
        class.

        Any keyword arguments passed to this method will be passed on to
        the constructor method when creating the panel instance.
        """
        field_or_attr = get_model_field_or_attribute(self.model, value)

        if isinstance(field_or_attr, reverse_related.ManyToOneRel) and isinstance(
            field_or_attr.field, ParentalKey
        ):
            return self.create_inline_panel(value, **kwargs)

        klass = self.get_panel_class(value, field_or_attr)
        return klass(value, **kwargs)

    def create_panel_from_tuple(self, value, **kwargs):
        """
        Return a panel instance appropriate for the provided tuple of values.

        Any keyword arguments passed to this method will be passed on to
        the constructor method when creating the panel instance.

        Tuples can be used in panel definitions to define sevral things:

        1.  A standard field panel with an alterative widget instance or class.
            For example:

            ('field_name', WidgetClass(key=value))
            ('field_name', WidgetClass)

        2.  A MultiFieldPanel with a heading value, optional classname,
            and a list of fields/panels to include as children. For example:

            ('heading', ['field_one', 'field_two'])
            ('heading', 'classname', ['field_one', 'field_two'])

        3.  An InlinePanel with a relationship name, optional
            heading value, and a list of fields/panels to include. For example:

            ('relation_name', ['field_one', 'field_two'])
            ('relation_name', "Page categories", ['field_one', 'field_two'])

        4.  A FieldRowPanel, where each item is a field to be included.
            For example:

            ('field_one, ('field_two', CustomWidget), FieldPanel('field_three'))
        """
        first_item = value[0]
        last_item = value[-1]

        if isinstance(last_item, Widget) or issubclass(last_item, Widget):
            kwargs.update(
                widget=last_item,
                classname=value[1] if len(value) == 3 else kwargs.get("classname"),
            )
            return self.create_panel_from_string(first_item, **kwargs)

        if isinstance(last_item, list):
            try:
                field = get_model_field_or_attribute(self.model, first_item)
            except AttributeError:
                field = None

            if field:
                kwargs.update(
                    related_model=field.model,
                    panels=last_item,
                    heading=value[1] if len(value) == 3 else kwargs.get("heading"),
                )
                return self.create_inline_panel(first_item, **kwargs)
            elif field is None:
                kwargs.update(
                    heading=first_item,
                    children=last_item,
                    classname=value[1] if len(value) == 3 else kwargs.get("classname"),
                )
                return self.create_multifield_panel(**kwargs)
            return

        return self.create_row_panel(value, **kwargs)

    def create_panel_from_dict(self, value, **kwargs):
        return

    def create_tab(self, definition, **kwargs):
        if isinstance(definition, tuple):
            return self.create_tab_from_tuple(definition, **kwargs)
        if isinstance(definition, dict):
            return self.create_tab_from_dict(definition, **kwargs)
        if isinstance(definition, ObjectList):
            return definition

    def create_tab_from_tuple(self, value, **kwargs):
        kwargs.update(
            heading=value[0],
            children=value[-1],
            classname=value[1] if len(value) == 3 else None,
        )
        return self.get_tab_class()(**kwargs)

    def create_tab_from_dict(self, value, **kwargs):
        kwargs.update(value)
        return self.get_tab_class()(**kwargs)

    def get_panel_definitions(self):
        definitions = self.children or self.panels or getattr(self.model, "panels", ())
        if definitions:
            return definitions
        return list(get_editable_field_names_for_model(self.model, exclude=self.exclude_fields))

    def get_panels(self):
        """
        Generator that returns unbound FieldPanel, InlinePanel, FieldRowPanel and
        MultiFieldPanel instances from a mixed sequence of field names, panel
        instances, and tuples.
        """
        for value in self.get_panel_definitions():
            panel = self.create_panel(value)
            if panel is not None:
                yield panel

    def get_tab_definitions(self):
        return ()

    def get_tabs(self):
        """
        Generator that returns unbound tab (ObjectList) instances from
        from a mixed sequence of definitions in tuple or dict format,
        and existing tab instances.
        """
        for value in self.get_tab_definitions():
            tab = self.create_tab(value)
            if tab is not None:
                yield tab

    def get_row_panel_class(self):
        return self.row_panel_class or FieldRowPanel

    def get_multifield_panel_class(self):
        return self.multifield_panel_class or MultiFieldPanel

    def get_inline_panel_class(self):
        return self.inline_panel_class or InlinePanel

    def get_tab_class(self):
        return self.inline_panel_class or ObjectList

    def create_row_panel(self, children, **kwargs):
        kwargs["children"] = children
        return self.get_row_panel_class()(**kwargs)

    def create_multifield_panel(self, heading, children, **kwargs):
        kwargs.update(heading=heading, children=children)
        return self.get_multifield_panel_class()(**kwargs)

    def create_inline_panel(self, rel_name, panels=None, **kwargs):
        kwargs["panels"] = panels
        return self.get_inline_panel_class()(rel_name, **kwargs)

    def on_model_bound(self):
        self.children = [child.bind_to(model=self.model) for child in self.get_panels()]

    def on_instance_bound(self):
        self.children = [child.bind_to(instance=self.instance)
                         for child in self.children]

    def on_request_bound(self):
        self.children = [child.bind_to(request=self.request)
                         for child in self.children]

    def on_form_bound(self):
        children = []
        for child in self.children:
            if isinstance(child, FieldPanel):
                if self.form._meta.exclude:
                    if child.field_name in self.form._meta.exclude:
                        continue
                if self.form._meta.fields:
                    if child.field_name not in self.form._meta.fields:
                        continue
            children.append(child.bind_to(form=self.form))
        self.children = children

    def render(self):
        return mark_safe(render_to_string(self.template, {
            'self': self
        }))

    def get_comparison(self):
        comparators = []

        for child in self.children:
            comparators.extend(child.get_comparison())

        return comparators


class BaseFormEditHandler(BaseCompositeEditHandler):
    """
    Base class for edit handlers that can construct a form class for all their
    child edit handlers.
    """

    # The form class used as the base for constructing specific forms for this
    # edit handler.  Subclasses can override this attribute to provide a form
    # with custom validation, for example.  Custom forms must subclass
    # WagtailAdminModelForm
    base_form_class = None

    def get_form_class(self):
        """
        Construct a form class that has all the fields and formsets named in
        the children of this edit handler.
        """
        if self.model is None:
            raise AttributeError(
                '%s is not bound to a model yet. Use `.bind_to(model=model)` '
                'before using this method.' % self.__class__.__name__)

        # If a custom form class was passed to the EditHandler, use it.
        # Otherwise, use the base_form_class from the model.
        # If that is not defined, use WagtailAdminModelForm.
        model_form_class = getattr(self.model, "base_form_class", WagtailAdminModelForm)
        base_form_class = self.base_form_class or model_form_class

        return get_form_for_model(
            self.model,
            form_class=base_form_class,
            fields=self.required_fields(),
            formsets=self.required_formsets(),
            widgets=self.widget_overrides())


class TabbedInterface(BaseFormEditHandler):
    template = "wagtailadmin/edit_handlers/tabbed_interface.html"
    tab_definitions = None

    def __init__(self, *args, **kwargs):
        self.base_form_class = kwargs.pop('base_form_class', None)
        super().__init__(*args, **kwargs)

    def clone_kwargs(self):
        kwargs = super().clone_kwargs()
        kwargs['base_form_class'] = self.base_form_class
        return kwargs

    def get_tab_definitions(self):
        return self.children or self.tab_definitions or getattr(self.model, "tab_definitions", ())

    def on_model_bound(self):
        self.children = [child.bind_to(model=self.model) for child in self.get_tabs()]


class ObjectList(TabbedInterface):
    template = "wagtailadmin/edit_handlers/object_list.html"

    def on_model_bound(self):
        self.children = [child.bind_to(model=self.model) for child in self.get_panels()]


class PageTabbedInterface(TabbedInterface):
    content_panels = None
    promote_panels = None
    settings_panels = None
    extra_tab_definitions = None

    def get_content_panels(self):
        if self.content_panels is not None:
            return self.content_panels
        return getattr(self.model, "content_panels", None)

    def get_promote_panels(self):
        if self.promote_panels is not None:
            return self.promote_panels
        return getattr(self.model, "promote_panels", None)

    def get_settings_panels(self):
        if self.settings_panels is not None:
            return self.settings_panels
        return getattr(self.model, "settings_panels", None)

    def get_extra_tab_definitions(self):
        if self.extra_tab_definitions is not None:
            return self.extra_tab_definitions
        return getattr(self.model, "extra_tab_definitions", None)

    def get_tab_definitions(self):
        # Respect 'children' if provided at initialisation, or allow
        # a 'tab_definitions' value on this class (or the model class)
        # to completely override things
        definitions = super().get_tab_definitions()
        if definitions:
            return definitions

        definitions = []
        content_panels = self.get_content_panels()
        if content_panels:
            definitions.append((gettext_lazy("Content"), content_panels))

        promote_panels = self.get_promote_panels()
        if promote_panels:
            definitions.append((gettext_lazy("Promote"), promote_panels))

        extra_tab_definitions = self.get_extra_tab_definitions()
        if extra_tab_definitions:
            definitions.extend(extra_tab_definitions)

        settings_panels = self.get_settings_panels()
        if settings_panels:
            definitions.append((gettext_lazy("Settings"), "settings", settings_panels))
        return definitions


class FieldRowPanel(BaseCompositeEditHandler):
    template = "wagtailadmin/edit_handlers/field_row_panel.html"

    def on_instance_bound(self):
        super().on_instance_bound()

        col_count = ' col%s' % (12 // len(self.children))
        # If child panel doesn't have a col# class then append default based on
        # number of columns
        for child in self.children:
            if not re.search(r'\bcol\d+\b', child.classname):
                child.classname += col_count


class MultiFieldPanel(BaseCompositeEditHandler):
    template = "wagtailadmin/edit_handlers/multi_field_panel.html"

    def classes(self):
        classes = super().classes()
        classes.append("multi-field")
        return classes


class HelpPanel(EditHandler):
    def __init__(self, content='', template='wagtailadmin/edit_handlers/help_panel.html',
                 heading='', classname=''):
        super().__init__(heading=heading, classname=classname)
        self.content = content
        self.template = template

    def clone_kwargs(self):
        kwargs = super().clone_kwargs()
        del kwargs['help_text']
        kwargs.update(
            content=self.content,
            template=self.template,
        )
        return kwargs

    def render(self):
        return mark_safe(render_to_string(self.template, {
            'self': self
        }))


class FieldPanel(EditHandler):
    TEMPLATE_VAR = 'field_panel'

    def __init__(self, field_name, *args, **kwargs):
        widget = kwargs.pop('widget', None)
        if widget is not None:
            self.widget = widget
        super().__init__(*args, **kwargs)
        self.field_name = field_name

    def clone_kwargs(self):
        kwargs = super().clone_kwargs()
        kwargs.update(
            field_name=self.field_name,
            widget=self.widget if hasattr(self, 'widget') else None,
        )
        return kwargs

    def widget_overrides(self):
        """check if a specific widget has been defined for this field"""
        if hasattr(self, 'widget'):
            return {self.field_name: self.widget}
        return {}

    def classes(self):
        classes = super().classes()

        if self.bound_field.field.required:
            classes.append("required")
        if self.bound_field.errors:
            classes.append("error")

        classes.append(self.field_type())

        return classes

    def field_type(self):
        return camelcase_to_underscore(self.bound_field.field.__class__.__name__)

    def id_for_label(self):
        return self.bound_field.id_for_label

    object_template = "wagtailadmin/edit_handlers/single_field_panel.html"

    def render_as_object(self):
        return mark_safe(render_to_string(self.object_template, {
            'self': self,
            self.TEMPLATE_VAR: self,
            'field': self.bound_field,
        }))

    field_template = "wagtailadmin/edit_handlers/field_panel_field.html"

    def render_as_field(self):
        return mark_safe(render_to_string(self.field_template, {
            'field': self.bound_field,
            'field_type': self.field_type(),
        }))

    def required_fields(self):
        return [self.field_name]

    def get_comparison_class(self):
        # Hide fields with hidden widget
        widget_override = self.widget_overrides().get(self.field_name, None)
        if widget_override and widget_override.is_hidden:
            return

        try:
            field = self.db_field

            if field.choices:
                return compare.ChoiceFieldComparison

            if field.is_relation:
                if isinstance(field, TaggableManager):
                    return compare.TagsFieldComparison
                elif field.many_to_many:
                    return compare.M2MFieldComparison

                return compare.ForeignObjectComparison

            if isinstance(field, RichTextField):
                return compare.RichTextFieldComparison

            if isinstance(field, (CharField, TextField)):
                return compare.TextFieldComparison

        except FieldDoesNotExist:
            pass

        return compare.FieldComparison

    def get_comparison(self):
        comparator_class = self.get_comparison_class()

        if comparator_class:
            try:
                return [functools.partial(comparator_class, self.db_field)]
            except FieldDoesNotExist:
                return []
        return []

    @cached_property
    def db_field(self):
        try:
            model = self.model
        except AttributeError:
            raise ImproperlyConfigured("%r must be bound to a model before calling db_field" % self)

        return model._meta.get_field(self.field_name)

    def on_form_bound(self):
        self.bound_field = self.form[self.field_name]
        self.heading = self.heading or self.bound_field.label
        self.help_text = self.bound_field.help_text

    def __repr__(self):
        return "<%s '%s' with model=%s instance=%s request=%s form=%s>" % (
            self.__class__.__name__, self.field_name,
            self.model, self.instance, self.request, self.form.__class__.__name__)


class RichTextFieldPanel(FieldPanel):
    def get_comparison_class(self):
        return compare.RichTextFieldComparison


class ReadOnlyPanel(EditHandler):
    """
    A panel that can be used to display an attribute value from the
    current instance, named by ``attr_name``. The attribute can be a
    field, property method, or standard method that only takes a single
    ``self`` or ``cls`` argument.

    This panel uses the same templates as ``FieldPanel`` to allow it to
    be used in much the same way. Only, instead of adding a ``BoundField``
    instance to the context as ``field``, it adds itself.
    """

    object_template = "wagtailadmin/edit_handlers/single_field_panel.html"
    field_template = "wagtailadmin/edit_handlers/field_panel_field.html"
    value_template = "wagtailadmin/edit_handlers/readonly_value.html"

    def __init__(self, attr_name, template=None, **kwargs):
        super().__init__(**kwargs)
        self.attr_name = attr_name
        if template is not None:
            self.value_template = template
        self.value = kwargs.get('value')

    def clone_kwargs(self):
        kwargs = super().clone_kwargs()
        kwargs.update(
            attr_name=self.attr_name, template=self.value_template, value=self.value
        )
        return kwargs

    def on_instance_bound(self):
        attr = getattr(self.instance, self.attr_name)

        # set self.value
        if callable(attr):
            self.value = attr()
        self.value = attr

        # set self.heading
        if not self.heading:
            if hasattr(attr, "short_description"):
                self.heading = attr.short_description
            else:
                self.heading = capfirst(self.attr_name)

    def label_tag(self):
        # Mimics BoundField.label_tag()
        return format_html('<label id="{}">{}</label>', self.id_for_label, self.heading)

    def id_for_label(self):
        # Mimics BoundField.id_for_label()
        return f"id_{self.attr_name.lower()}"

    def value_as_html(self):
        return mark_safe(
            render_to_string(
                self.template,
                {
                    "id": self.id_for_label(),
                    "instance": self.instance,
                    "attr_name": self.attr_name,
                    "value": self.value,
                },
            )
        )

    def render_as_object(self):
        return mark_safe(
            render_to_string(
                self.object_template,
                {"self": self, FieldPanel.TEMPLATE_VAR: self, "field": self},
            )
        )

    def render_as_field(self):
        return mark_safe(
            render_to_string(
                self.field_template, {"field": self, "field_type": "readonly"}
            )
        )


class BaseChooserPanel(FieldPanel):
    """
    Abstract superclass for panels that provide a modal interface for choosing (or creating)
    a database object such as an image, resulting in an ID that is used to populate
    a hidden foreign key input.

    Subclasses provide:
    * field_template (only required if the default template of field_panel_field.html is not usable)
    * object_type_name - something like 'image' which will be used as the var name
      for the object instance in the field_template
    """

    def get_chosen_item(self):
        field = self.instance._meta.get_field(self.field_name)
        related_model = field.remote_field.model
        try:
            return getattr(self.instance, self.field_name)
        except related_model.DoesNotExist:
            # if the ForeignKey is null=False, Django decides to raise
            # a DoesNotExist exception here, rather than returning None
            # like every other unpopulated field type. Yay consistency!
            return

    def render_as_field(self):
        instance_obj = self.get_chosen_item()
        context = {
            'field': self.bound_field,
            self.object_type_name: instance_obj,
            'is_chosen': bool(instance_obj),  # DEPRECATED - passed to templates for backwards compatibility only
        }
        return mark_safe(render_to_string(self.field_template, context))


class PageChooserPanel(BaseChooserPanel):
    object_type_name = "page"

    def __init__(self, field_name, page_type=None, can_choose_root=False):
        super().__init__(field_name=field_name)

        if page_type:
            # Convert single string/model into list
            if not isinstance(page_type, (list, tuple)):
                page_type = [page_type]
        else:
            page_type = []

        self.page_type = page_type
        self.can_choose_root = can_choose_root

    def clone_kwargs(self):
        return {
            'field_name': self.field_name,
            'page_type': self.page_type,
            'can_choose_root': self.can_choose_root,
        }

    def widget_overrides(self):
        return {self.field_name: widgets.AdminPageChooser(
            target_models=self.target_models(),
            can_choose_root=self.can_choose_root)}

    def target_models(self):
        if self.page_type:
            target_models = []

            for page_type in self.page_type:
                try:
                    target_models.append(resolve_model_string(page_type))
                except LookupError:
                    raise ImproperlyConfigured(
                        "{0}.page_type must be of the form 'app_label.model_name', given {1!r}".format(
                            self.__class__.__name__, page_type
                        )
                    )
                except ValueError:
                    raise ImproperlyConfigured(
                        "{0}.page_type refers to model {1!r} that has not been installed".format(
                            self.__class__.__name__, page_type
                        )
                    )

            return target_models
        return [self.db_field.remote_field.model]


class InlinePanel(EditHandler):
    def __init__(self, relation_name, panels=None, heading='', label='',
                 min_num=None, max_num=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.relation_name = relation_name
        self.panels = panels
        self.heading = heading or label
        self.label = label
        self.min_num = min_num
        self.max_num = max_num
        self.child_edit_handler = MultiFieldPanel(self.panels, heading=self.heading)

    def clone_kwargs(self):
        kwargs = super().clone_kwargs()
        kwargs.update(
            relation_name=self.relation_name,
            panels=self.panels,
            label=self.label,
            min_num=self.min_num,
            max_num=self.max_num,
        )
        return kwargs

    def required_formsets(self):
        return {
            self.relation_name: {
                "fields": self.child_edit_handler.required_fields(),
                "widgets": self.child_edit_handler.widget_overrides(),
                "min_num": self.min_num,
                "validate_min": self.min_num is not None,
                "max_num": self.max_num,
                "validate_max": self.max_num is not None,
            }
        }

    def html_declarations(self):
        return self.child_edit_handler.html_declarations()

    def get_comparison(self):
        field_comparisons = []

        for panel in self.get_panels():
            field_comparisons.extend(
                panel.bind_to(model=self.db_field.related_model).get_comparison()
            )

        return [
            functools.partial(
                compare.ChildRelationComparison, self.db_field, field_comparisons
            )
        ]

    def on_model_bound(self):
        manager = getattr(self.model, self.relation_name)
        self.db_field = manager.rel
        # at this point, the MultiFieldPanel will create it's own panels
        self.child_edit_handler = self.child_edit_handler.bind_to(model=self.db_field.model)

    def on_form_bound(self):
        self.formset = self.form.formsets[self.relation_name]

        self.children = []
        for subform in self.formset.forms:
            # override the DELETE field to have a hidden input
            subform.fields[DELETION_FIELD_NAME].widget = forms.HiddenInput()

            # ditto for the ORDER field, if present
            if self.formset.can_order:
                subform.fields[ORDERING_FIELD_NAME].widget = forms.HiddenInput()

            self.children.append(
                self.child_edit_handler.bind_to(
                    instance=subform.instance, request=self.request, form=subform
                )
            )

        # if this formset is valid, it may have been re-ordered; respect that
        # in case the parent form errored and we need to re-render
        if self.formset.can_order and self.formset.is_valid():
            self.children.sort(
                key=lambda child: child.form.cleaned_data[ORDERING_FIELD_NAME] or 1
            )

        empty_form = self.formset.empty_form
        empty_form.fields[DELETION_FIELD_NAME].widget = forms.HiddenInput()
        if self.formset.can_order:
            empty_form.fields[ORDERING_FIELD_NAME].widget = forms.HiddenInput()

        self.empty_child = self.child_edit_handler
        self.empty_child = self.empty_child.bind_to(
            instance=empty_form.instance, request=self.request, form=empty_form
        )

    template = "wagtailadmin/edit_handlers/inline_panel.html"

    def render(self):
        formset = render_to_string(
            self.template, {"self": self, "can_order": self.formset.can_order}
        )
        js = self.render_js_init()
        return widget_with_script(formset, js)

    js_template = "wagtailadmin/edit_handlers/inline_panel.js"

    def render_js_init(self):
        return mark_safe(
            render_to_string(
                self.js_template, {"self": self, "can_order": self.formset.can_order}
            )
        )


# This allows users to include the publishing panel in their own per-model override
# without having to write these fields out by hand, potentially losing 'classname'
# and therefore the associated styling of the publishing panel
class PublishingPanel(MultiFieldPanel):
    def __init__(self, **kwargs):
        updated_kwargs = {
            'children': [
                FieldRowPanel([
                    FieldPanel('go_live_at'),
                    FieldPanel('expire_at'),
                ], classname="label-above"),
            ],
            'heading': gettext_lazy('Scheduled publishing'),
            'classname': 'publishing',
        }
        updated_kwargs.update(kwargs)
        super().__init__(**updated_kwargs)


class PrivacyModalPanel(EditHandler):
    def __init__(self, **kwargs):
        updated_kwargs = {"heading": gettext_lazy("Privacy"), "classname": "privacy"}
        updated_kwargs.update(kwargs)
        super().__init__(**updated_kwargs)

    def render(self):
        content = render_to_string('wagtailadmin/pages/privacy_switch_panel.html', {
            'self': self,
            'page': self.instance,
            'request': self.request
        })

        from wagtail.admin.staticfiles import versioned_static
        return mark_safe('{0}<script type="text/javascript" src="{1}"></script>'.format(
            content,
            versioned_static('wagtailadmin/js/privacy-switch.js'))
        )


# Now that we've defined EditHandlers, we can set up wagtailcore.Page to have some.
Page.content_panels = [
    FieldPanel('title', classname="full title"),
]

Page.promote_panels = [
    MultiFieldPanel([
        FieldPanel('slug'),
        FieldPanel('seo_title'),
        FieldPanel('show_in_menus'),
        FieldPanel('search_description'),
    ], gettext_lazy('Common page configuration')),
]

Page.settings_panels = [
    PublishingPanel(),
    PrivacyModalPanel(),
]

Page.base_form_class = WagtailAdminPageForm


def get_page_edit_handler(cls, instance=None, request=None):
    return PageTabbedInterface().bind_to(model=cls, instance=instance, request=request)


Page.get_edit_handler = types.MethodType(get_page_edit_handler, Page)


class StreamFieldPanel(FieldPanel):
    def classes(self):
        classes = super().classes()
        classes.append("stream-field")

        # In case of a validation error, BlockWidget will take care of outputting the error on the
        # relevant sub-block, so we don't want the stream block as a whole to be wrapped in an 'error' class.
        if 'error' in classes:
            classes.remove("error")

        return classes

    def html_declarations(self):
        return self.block_def.all_html_declarations()

    def get_comparison_class(self):
        return compare.StreamFieldComparison

    def id_for_label(self):
        # a StreamField may consist of many input fields, so it's not meaningful to
        # attach the label to any specific one
        return ""

    def on_model_bound(self):
        super().on_model_bound()
        self.block_def = self.db_field.stream_block
