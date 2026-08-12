import uuid
from django.db import models
from apps.workspaces.models import MarketingWorkspace

class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(MarketingWorkspace, on_delete=models.CASCADE, related_name='audit_logs')
    date = models.DateTimeField(auto_now_add=True)
    user = models.CharField(max_length=255)
    platform = models.CharField(max_length=100)
    account = models.CharField(max_length=255)
    action = models.CharField(max_length=255)
    previous_state = models.CharField(max_length=100, blank=True, null=True)
    next_state = models.CharField(max_length=100, blank=True, null=True)
    result = models.CharField(max_length=50) # 'Success', 'Failed'
    error = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'audit_logs'
