# -*- coding: utf-8 -*-
from django.db import migrations
from django.db.models import Count, Q
from wagtail.models import Page as RealPage


def create_default_tenant(apps, schema_editor):
    Tenant = apps.get_model("wagtailcore.Tenant")
    Tenant.objects.create(label="Default", is_default=True, is_open=True)


class Migration(migrations.Migration):

    dependencies = [
        ("wagtailcore", "0077_tenant_sharedtenantmember"),
    ]

    operations = [
        migrations.RunPython(create_default_tenant, migrations.RunPython.noop),
    ]
