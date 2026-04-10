"""
ASGI config for clama_backend project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""
import os
import sys
from pathlib import Path

from django.core.asgi import get_asgi_application

# This allows easy placement of apps within the interior
# clama_backend directory.
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR / "clama_backend"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

application = get_asgi_application()
