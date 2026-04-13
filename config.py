"""Configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Project repos to scan
PROJECT_REPOS = [
    p.strip()
    for p in os.getenv("PROJECT_REPOS", "").split(",")
    if p.strip()
]

# Telegram notifications
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Output
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "output"))
DRAFTS_DIR = os.path.join(OUTPUT_DIR, "drafts")
INSIGHTS_DIR = os.path.join(OUTPUT_DIR, "insights")
PLANS_DIR = os.path.join(OUTPUT_DIR, "plans")

# Voice profile
VOICE_PROFILE_PATH = os.path.join(os.path.dirname(__file__), "voice_profile.yaml")
VOICE_SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "voice_samples")

# Database
DB_PATH = os.path.join(os.path.dirname(__file__), "brand_agent.db")

# Ensure output dirs exist
for d in [DRAFTS_DIR, INSIGHTS_DIR, PLANS_DIR]:
    os.makedirs(d, exist_ok=True)
