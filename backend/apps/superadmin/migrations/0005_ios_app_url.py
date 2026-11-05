from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("superadmin", "0004_android_app_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformsettings",
            name="ios_app_url",
            field=models.URLField(
                blank=True,
                help_text="App Store or TestFlight public link. Leave empty to send iPhone users to the web app.",
                verbose_name="iPhone app link",
            ),
        ),
    ]
