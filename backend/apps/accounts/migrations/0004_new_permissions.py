from django.db import migrations

NEW = {"Owner": ["shifts", "marketing", "export"], "Manager": ["shifts", "marketing", "export"], "Cashier": ["shifts"]}


def forwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.filter(is_system=True, name__in=NEW):
        perms = list(role.permissions or [])
        for p in NEW[role.name]:
            if p not in perms:
                perms.append(p)
        role.permissions = perms
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_audit_log")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
