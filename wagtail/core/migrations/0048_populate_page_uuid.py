# -*- coding: utf-8 -*-
import uuid
from django.db import migrations


def migrate_forwards(apps, schema_editor):
    Page = apps.get_model('wagtailcore.Page')

    # used to keep small batches of pages in memory
    # to utilise bulk_update()
    batch = []

    for page in Page.objects.all().only('id', 'url_path').iterator():

        # generate uuid from 'url_path' for similar results accross environments
        page.uuid = uuid.uuid3(uuid.NAMESPACE_URL, page.url_path)
        batch.append(page)

        if len(batch) == 150:
            # save and reset current batch
            Page.objects.bulk_update(batch, ['uuid'])
            batch.clear()

    # save any leftovers
    if batch:
        Page.objects.bulk_update(batch, ['uuid'])


def migrate_backwards(apps, schema_editor):
    Page = apps.get_model('wagtailcore.Page')
    Page.objects.all().update(uuid=None)


class Migration(migrations.Migration):

    dependencies = [
        ('wagtailcore', '0047_add_page_uuid'),
    ]

    operations = [
        migrations.RunPython(migrate_forwards, migrate_backwards),
    ]
