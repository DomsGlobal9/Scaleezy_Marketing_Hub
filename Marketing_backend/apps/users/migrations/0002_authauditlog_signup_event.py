"""SIGNUP joins the auth audit events. Choices only; no data changes."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='authauditlog',
            name='event',
            field=models.CharField(
                choices=[
                    ('LOGIN_SUCCESS', 'Login succeeded'),
                    ('LOGIN_FAILED', 'Login failed'),
                    ('TOKEN_REFRESH', 'Token refreshed'),
                    ('TOKEN_REFRESH_FAILED', 'Token refresh failed'),
                    ('LOGOUT', 'Logged out'),
                    ('ACCESS_DENIED', 'Access denied'),
                    ('SIGNUP', 'Signed up'),
                ],
                max_length=32,
            ),
        ),
    ]
