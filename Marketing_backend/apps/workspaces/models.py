import uuid
from django.db import models

class MarketingWorkspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer_id = models.CharField(max_length=255, help_text="Reference to the customer/tenant in the main system")
    workspace_name = models.CharField(max_length=255)
    timezone = models.CharField(max_length=50, default='UTC')
    default_language = models.CharField(max_length=10, default='en')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'marketing_workspaces'

    def __str__(self):
        return self.workspace_name
