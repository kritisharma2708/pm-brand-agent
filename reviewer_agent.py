"""Reviewer Agent — quality gate with voice scoring and feedback injection."""

import json
from typing import Optional

import anthropic
import yaml

import config


def _load_voice_profile() -> dict:
    if config.VOICE_PROFILE_PATH and __import__("os").path.isfile(config.VOICE_PROFILE_PATH):
        with open(config.VOICE_PROFILE_PATH, "r") as f:
            return yaml.safe_load(f)
    return {}


def _build_review_prompt(voice: dict, platform: str) -> str:
    platform_voice = voice.get(platform, {})
    anti_patterns = platform_voice.get("anti_patterns", [])
    dna = voice.get("voice_dna", {})

    return f"""You are a strict quality reviewer for social media posts.
Your ONLY job is to evaluate whether a draft post sounds authentic and matches
the author's voice. You are a critic, not a creator.

AUTHOR IDENTITY: {dna.get('identity', 'PM who builds with AI')}
PLATFORM: {platform}
EXPECTED TONE: {platform_voice.get('tone', 'Conversational')}

ANTI-PATTERNS TO CATCH:
{chr(10).join(f'- {p}' for p in anti_patterns)}

ADDITIONAL SLOP PATTERNS TO CATCH:
- "I'm excited to share..." or "Thrilled to announce..."
- "In today's fast-paced world..."
- "Here are N tips/lessons/ways..."
- Excessive hashtags (more than 3)
- Generic motivational filler
- Corporate jargon (leverage, synergy, ecosystem, empower)
- Sentences that could appear in anyone's post (not specific to this author)

EVALUATION CRITERIA:
1. VOICE MATCH (does it sound like the author's samples?)
2. TONE FIT (appropriate for {platform}?)
3. SPECIFICITY (references real projects/people/tools, not generic?)
4. AUTHENTICITY (honest, not performative?)
5. SLOP CHECK (any AI tells or generic filler?)

Respond with ONLY valid JSON in this exact format:
{{
    "score": <1-5>,
    "passed": <true if score >= 4, false otherwise>,
    "feedback": "<specific feedback explaining the score>",
    "suggestions": ["<specific suggestion 1>", "<specific suggestion 2>"],
    "slop_detected": ["<any slop phrases found>"]
}}

SCORING:
- 5: Sounds exactly like the author. Ready to post.
- 4: Good voice match. Minor tweaks possible but not needed.
- 3: Decent but something feels off. Needs human review with suggestions.
- 2: Doesn't sound like the author. Too generic/corporate/AI-sounding.
- 1: Completely off. Slop detected or fundamentally wrong tone."""


async def review_draft(
    draft: str,
    platform: str,
) -> dict:
    """Review a draft post for voice match and quality.

    Returns dict with: score (1-5), passed (bool), feedback (str),
    suggestions (list), slop_detected (list).
    """
    voice = _load_voice_profile()
    system_prompt = _build_review_prompt(voice, platform)

    # Load voice samples for comparison
    from content_agent import load_voice_samples
    samples = load_voice_samples()

    user_message = f"""Review this {platform} post draft:

---
{draft}
---"""

    if samples:
        user_message += f"""

Compare against these voice samples from the author:
{samples}"""

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()
        # Handle JSON wrapped in markdown code blocks
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(raw)
    except (json.JSONDecodeError, IndexError):
        return {
            "score": 3,
            "passed": False,
            "feedback": "Could not parse reviewer response. Flagging for manual review.",
            "suggestions": [],
            "slop_detected": [],
        }
    except anthropic.APIError as e:
        print(f"[ERROR] Reviewer Agent ({platform}): {e}")
        return {
            "score": 3,
            "passed": False,
            "feedback": f"Reviewer API error: {e}. Passing with warning.",
            "suggestions": [],
            "slop_detected": [],
        }


async def review_with_retry(
    draft: str,
    platform: str,
    project_context: str,
    content_mode: str,
    max_retries: int = 2,
) -> dict:
    """Review a draft and retry content generation if score is 1-2.

    Returns dict with: final_draft (str), review (dict), retries (int).
    """
    from content_agent import generate_post

    current_draft = draft
    retries = 0

    for attempt in range(max_retries + 1):
        review = await review_draft(current_draft, platform)

        if review["score"] >= 3:
            return {
                "final_draft": current_draft,
                "review": review,
                "retries": retries,
            }

        if attempt < max_retries:
            # Inject reviewer feedback into Content Agent retry
            feedback = review["feedback"]
            if review["suggestions"]:
                feedback += "\nSpecific suggestions: " + "; ".join(review["suggestions"])
            if review["slop_detected"]:
                feedback += "\nSlop to remove: " + ", ".join(review["slop_detected"])

            new_draft = await generate_post(
                project_context=project_context,
                platform=platform,
                content_mode=content_mode,
                reviewer_feedback=feedback,
            )

            if new_draft:
                current_draft = new_draft
                retries += 1
            else:
                break

    # Max retries exhausted — return best attempt with warning
    review["feedback"] = f"[WARNING: {retries} retries exhausted] " + review["feedback"]
    return {
        "final_draft": current_draft,
        "review": review,
        "retries": retries,
    }
