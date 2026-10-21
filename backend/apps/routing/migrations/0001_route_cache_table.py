"""Create the database cache table used for routing responses.

``createcachetable`` is idempotent and does nothing for non-database cache backends,
so ``migrate`` is the only setup step needed.
"""

from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):
    dependencies = []

    operations = [migrations.RunPython(create_cache_table, migrations.RunPython.noop)]
