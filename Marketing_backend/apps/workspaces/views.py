from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from .models import MarketingWorkspace
from .serializers import MarketingWorkspaceSerializer, AuditLogSerializer
from apps.audit.models import AuditLog

class MarketingWorkspaceViewSet(viewsets.ModelViewSet):
    queryset = MarketingWorkspace.objects.all()
    serializer_class = MarketingWorkspaceSerializer
    permission_classes = [AllowAny]


class WorkspaceSettingsView(APIView):
    def get(self, request):
        workspace = MarketingWorkspace.objects.first()
        if not workspace:
            return Response({"error": "No workspace found"}, status=404)
        
        audit_logs = AuditLog.objects.filter(workspace=workspace).order_by('-date')[:50]
        
        return Response({
            "workspace": MarketingWorkspaceSerializer(workspace).data,
            "audit_logs": AuditLogSerializer(audit_logs, many=True).data
        })

    def put(self, request):
        workspace = MarketingWorkspace.objects.first()
        if not workspace:
            return Response({"error": "No workspace found"}, status=404)
            
        serializer = MarketingWorkspaceSerializer(workspace, data=request.data.get('workspace', request.data), partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"workspace": serializer.data})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
