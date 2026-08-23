"""
Concurrency-safe "one company, one enrolment".

A new table with a UNIQUE host, written inside the signup transaction. Nothing
existing is altered and nothing is backfilled: pre-existing clients keep their
websites, and the serializer's friendly check still covers them; this row is
only what two simultaneous signups cannot both get past.
"""
import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_authauditlog_signup_event'),
        ('workspaces', '0004_workspace_approval_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='SignupWebsiteClaim',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('website_host', models.CharField(max_length=253, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='signup_website_claims', to='workspaces.marketingworkspace')),
            ],
            options={'db_table': 'signup_website_claims'},
        ),
    ]
