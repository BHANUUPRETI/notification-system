from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0002_template_provider_status_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="template",
            name="provider_template_id",
            field=models.CharField(blank=True, editable=False, help_text="WhatsApp only: Meta template id populated by Sync.", max_length=120),
        ),
        migrations.AddField(
            model_name="template",
            name="variable_mapping",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Maps template variables to controlled application fields, e.g. {"first_name": "user.first_name"}.',
            ),
        ),
        migrations.AddField(
            model_name="notificationlog",
            name="provider_response",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="notificationlog",
            name="dedupe_key",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AddField(
            model_name="notificationlog",
            name="sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
