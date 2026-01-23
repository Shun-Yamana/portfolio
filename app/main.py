import json
import os
import time


def lambda_handler(event, context):
    """Minimal health responder for connectivity checks."""
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "ok": True,
            "ts": int(time.time()),
            "requestId": getattr(context, "aws_request_id", None),
            "sourceIp": event.get("requestContext", {}).get("http", {}).get("sourceIp"),
            "path": event.get("rawPath"),
        }),
    }
