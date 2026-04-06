"""Content Agent — generates LinkedIn + Twitter posts using Claude API."""

import asyncio
import os
from typing import Optional

import anthropic
import yaml

import config


def load_voice_profile() -> dict:
    """Load voice profile from YAML. Falls back to minimal defaults."""
    if os.path.isfile(config.VOICE_PROFILE_PATH):
        with open(config.VOICE_PROFILE_PATH, "r") as f:
            return yaml.safe_load(f)
    return {
        "linkedin": {"tone": "Professional but human", "anti_patterns": []},
        "twitter": {"tone": "Punchy and witty", "anti_patterns": []},
        "voice_dna": {"identity": "PM who builds with AI"},
    }


def load_voice_samples() -> str:
    """Load voice sample files as reference text for the prompt."""
    samples = []
    if not os.path.isdir(config.VOICE_SAMPLES_DIR):
        return ""
    for fname in sorted(os.listdir(config.VOICE_SAMPLES_DIR)):
        if fname.endswith(".md"):
            fpath = os.path.join(config.VOICE_SAMPLES_DIR, fname)
            with open(fpath, "r") as f:
                samples.append(f"--- {fname} ---\n{f.read().strip()}")
    return "\n\n".join(samples)


def _build_system_prompt(platform: str, voice: dict, samples: str, insight: Optional[str] = None) -> str:
    """Build the system prompt for content generation."""
    platform_voice = voice.get(platform, {})
    dna = voice.get("voice_dna", {})

    anti_patterns = "\n".join(f"  - {p}" for p in platform_voice.get("anti_patterns", []))
    structure = "\n".join(f"  - {s}" for s in platform_voice.get("structure", []))
    signature = "\n".join(f"  - {s}" for s in platform_voice.get("signature_moves", []))

    prompt = f"""You are a ghostwriter for a PM who builds AI-powered projects.
Your job is to generate a {platform} post that sounds exactly like the author.

VOICE IDENTITY: {dna.get('identity', 'PM who ships with AI')}
PERSPECTIVE: {dna.get('perspective', 'Practitioner, not pundit')}
HUMOR STYLE: {dna.get('humor', 'Self-deprecating, relatable')}
TONE: {platform_voice.get('tone', 'Conversational')}

POST STRUCTURE:
{structure}

SIGNATURE MOVES (use these naturally, don't force them):
{signature}

NEVER DO THESE:
{anti_patterns}

CRITICAL RULES:
- Sound like a real person, not a content mill
- Reference specific project names, tools, and people
- Be honest about what didn't work, not just what did
- No hashtags in the post body (add 2-3 at the very end if LinkedIn)
- Every claim must be grounded in the project context provided
- Do NOT hallucinate features, metrics, or accomplishments not in the context"""

    if samples:
        prompt += f"""

VOICE SAMPLES (match this writing style):
{samples}"""

    if insight:
        prompt += f"""

LEARNING INSIGHT (from engagement analysis — lean into what works):
{insight}"""

    return prompt


def _build_user_prompt(project_context: str, content_mode: str, hot_take: Optional[str] = None) -> str:
    """Build the user message for content generation."""
    if content_mode == "short_linkedin":
        return f"""Generate a SHORT LinkedIn post — max 4-6 lines. One insight, one punchline.
Think: a single observation or hot take that makes someone stop scrolling.
No numbered lists. No headers. No "Here's what I learned." Just one sharp thought.
Examples of the right length:
- "Everyone's building AI features. Almost nobody's building AI infrastructure. That's where the real opportunity is."
- "Spent 3 hours debugging a webhook. Turned out the URL had a trailing slash. Sometimes the bug is embarrassingly simple."

PROJECT CONTEXT (for inspiration — pick ONE tiny detail):
{project_context}"""

    if content_mode == "short_twitter":
        return f"""Generate a SHORT tweet — max 280 characters. One line. Punchy.
This should work as a standalone tweet, not a thread starter.
No hashtags. No "thread 🧵". Just one sharp observation or hot take.

PROJECT CONTEXT (for inspiration):
{project_context}"""

    if content_mode == "hot_take" and hot_take:
        return f"""Generate a post based on this thought/reaction:

"{hot_take}"

Connect it to relevant project experience where natural. Don't force the connection if there isn't one.

PROJECT CONTEXT (for grounding):
{project_context}"""

    if content_mode == "build_diary":
        return f"""Generate a "build diary" post — what was shipped recently, what was hard, what was learned.
Focus on the narrative: what's interesting about this work that others would find valuable?
Pick ONE specific project to focus on — don't try to cover everything.

PROJECT CONTEXT:
{project_context}"""

    if content_mode == "news_reaction":
        return f"""Generate a post reacting to this trending news/topic. Share your perspective as a PM who builds with AI.
You DON'T need to connect it to a specific project — focus on the insight, opinion, or hot take.
Only reference your projects if there's a genuine, natural connection. Don't force it.

TRENDING TOPIC:
{hot_take}

PROJECT CONTEXT (for reference only — use sparingly):
{project_context}"""

    if content_mode == "cross_project_learnings":
        return f"""Generate a post about patterns and learnings across MULTIPLE projects.
Don't focus on one project — look at what's common across all of them.
What's the meta-insight? What did building several AI tools teach you that building just one wouldn't?
Examples: common mistakes, surprising patterns, how your approach evolved, tools/techniques that work across projects.

PROJECT CONTEXT:
{project_context}"""

    if content_mode == "thought_leadership":
        return f"""Generate a thought-provoking post about the intersection of AI and product management.
This should be an OPINION or OBSERVATION — not a project showcase.
Draw from your experience building AI tools, but lead with the insight, not the project.
Be bold. Take a stance. Say something others aren't saying.

PROJECT CONTEXT (for grounding your perspective — don't make this about the projects):
{project_context}"""

    # Default: project showcase
    return f"""Generate a post showcasing recent project work. Pick the most interesting thing
from the context below and build a post around it. Focus on the insight or learning, not just what was built.

PROJECT CONTEXT:
{project_context}"""


async def generate_post(
    project_context: str,
    platform: str,
    content_mode: str = "build_diary",
    hot_take: Optional[str] = None,
    insight: Optional[str] = None,
    reviewer_feedback: Optional[str] = None,
) -> Optional[str]:
    """Generate a single post for a given platform.

    Args:
        project_context: Output from project_agent.build_project_context()
        platform: 'linkedin' or 'twitter'
        content_mode: 'build_diary', 'hot_take', or 'thoughtful'
        hot_take: Optional ad-hoc thought to react to
        insight: Optional learning insight from engagement analysis
        reviewer_feedback: Optional feedback from Reviewer Agent on a previous attempt

    Returns:
        Generated post text, or None on failure.
    """
    voice = load_voice_profile()
    samples = load_voice_samples()

    system_prompt = _build_system_prompt(platform, voice, samples, insight)
    user_prompt = _build_user_prompt(project_context, content_mode, hot_take)

    if reviewer_feedback:
        user_prompt += f"""

IMPORTANT — PREVIOUS ATTEMPT WAS REJECTED. Reviewer feedback:
{reviewer_feedback}
Please address this feedback in your new attempt."""

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text.strip()
    except anthropic.APIError as e:
        print(f"[ERROR] Content Agent ({platform}): {e}")
        return None


async def generate_posts(
    project_context: str,
    content_mode: str = "build_diary",
    hot_take: Optional[str] = None,
    insight: Optional[str] = None,
) -> list[dict]:
    """Generate posts for both platforms in parallel.

    Returns list of dicts with 'platform', 'content', 'content_mode'.
    """
    tasks = [
        generate_post(project_context, "linkedin", content_mode, hot_take, insight),
        generate_post(project_context, "twitter", content_mode, hot_take, insight),
    ]

    results = await asyncio.gather(*tasks)
    posts = []

    for platform, content in zip(["linkedin", "twitter"], results):
        if content:
            posts.append({
                "platform": platform,
                "content": content,
                "content_mode": content_mode,
            })

    return posts
