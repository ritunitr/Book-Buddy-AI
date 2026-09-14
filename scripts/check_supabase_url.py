#!/usr/bin/env python3
"""Verify Supabase URL is correct."""

import os
from dotenv import load_dotenv

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

print("=== Supabase Configuration ===")
print(f"URL: {url}")
print(f"Key (first 50 chars): {key[:50] if key else 'NOT SET'}...")
print()

if not url or not key:
    print("❌ Missing credentials in .env")
    exit(1)

# Verify URL format
if not url.startswith("https://") or not url.endswith(".supabase.co"):
    print("❌ URL format looks wrong. Should be: https://<project-ref>.supabase.co")
    exit(1)

print("✓ URL format looks correct")
print()
print("Next: Go to your Supabase Dashboard and verify:")
print("1. Project is initialized (green checkmark)")
print("2. Settings > API shows your Project URL")
print("3. Copy exact URL from dashboard if different")
