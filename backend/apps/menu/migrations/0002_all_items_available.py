"""Every menu item is permanently available: undo any sold-out / stock-count state."""
from django.db import migrations


def make_available(apps, schema_editor):
    Item = apps.get_model("menu", "Item")
    Item.objects.update(is_available=True, track_stock=False)


class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0001_initial"),
    ]

    operations = [migrations.RunPython(make_available, migrations.RunPython.noop)]
