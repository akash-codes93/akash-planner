"""
Supabase connection singleton for the akash-planner backend.

Loads environment variables via python-dotenv and returns a cached
supabase.Client instance. All agent tools and API routes import
get_supabase() from here — never construct the client directly.
"""

import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

_client: Client | None = None


def get_supabase() -> Client:
    """Return the cached Supabase client, creating it on first call.

    Reads SUPABASE_URL and SUPABASE_KEY from environment (loaded from
    backend/.env via python-dotenv at module import time).

    Raises:
        ValueError: if SUPABASE_URL or SUPABASE_KEY are not set.
    """
    global _client
    if _client is not None:
        return _client

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")

    if not url:
        raise ValueError(
            "SUPABASE_URL is not set. Copy backend/.env.example to backend/.env "
            "and fill in your Supabase project URL."
        )
    if not key:
        raise ValueError(
            "SUPABASE_KEY is not set. Copy backend/.env.example to backend/.env "
            "and fill in your Supabase anon public key."
        )

    _client = create_client(url, key)
    return _client
