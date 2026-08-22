from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('gemini', '0001_initial')]

    operations = [
        migrations.AlterField(
            model_name='geminigenerationrequest',
            name='prompt_data',
            field=models.TextField(
                blank=True,
                help_text='Provider-neutral generation brief',
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='geminigenerationrequest',
            name='provider',
            field=models.CharField(blank=True, default='', editable=False, max_length=50),
        ),
        migrations.AlterField(
            model_name='geminigenerationrequest',
            name='model',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
