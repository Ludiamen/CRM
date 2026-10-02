"""Проверка здоровья web (compose healthcheck): GET /health/ с именем хоста из PORTAL_URL.

Django отвечает только на хосты из ALLOWED_HOSTS (они выводятся из PORTAL_URL),
поэтому заголовок Host берётся оттуда же, а не «localhost».
"""
import os
import sys
import urllib.request
from urllib.parse import urlsplit

host = urlsplit(os.environ["PORTAL_URL"]).netloc
request = urllib.request.Request("http://127.0.0.1:8000/health/", headers={"Host": host})
try:
    with urllib.request.urlopen(request, timeout=3) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:  # noqa: BLE001 — любой отказ значит «нездоров»
    sys.exit(1)
