from rest_framework.response import Response

def APIResponse(success=True, data=None, message=None, error=None, status=200):
    payload = {
        "success": success,
    }
    if data is not None:
        payload["data"] = data
    if message is not None:
        payload["message"] = message
    if error is not None:
        payload["error"] = error
        
    return Response(payload, status=status)
