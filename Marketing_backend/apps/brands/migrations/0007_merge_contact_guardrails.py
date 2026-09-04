"""Join the original contact intake migration with the guardrails branch."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0006_brand_guardrails'),
        ('brands', '0006_brand_intake_contact'),
    ]

    operations = []
