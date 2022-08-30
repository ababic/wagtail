# -*- coding: utf-8 -*-
from django.db import migrations


def populate_wagtailgroups(apps, schema_editor):
    Group = apps.get_model("auth.Group")
    WagtailGroup = apps.get_model("wagtailusers.WagtailGroup")
    to_create = []
    for group in Group.objects.all():
        to_create.append(WagtailGroup(group=group))
    WagtailGroup.objects.bulk_create(to_create)


class Migration(migrations.Migration):

    dependencies = [
        ("wagtailusers", "0013_wagtailgroup"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(populate_wagtailgroups, migrations.RunPython.noop),
    ]
