"""
Content Council — Multi-platform content generation, refinement, and review.

This council:
1. Receives a topic, article, or video transcript
2. Drafts platform-specific posts (X, LinkedIn, Facebook, Instagram, Reddit, Discord)
3. Critiques the content for hook quality, platform fit, value density, and tone
4. Refines and synthesizes the output through debate
5. Submits for human approval before publishing
"""

from __future__ import annotations

import json
from src.core.council_base import BaseCouncil
from src.workflows.config.platform_specs import PLATFORM_SPECS, get_platform_prompt


class ContentCouncil(BaseCouncil):
    """Content Council: multi-agent content repurposing and creation engine."""

    council_name = "content"
    confidence_threshold = 85.0
    max_iterations = 3

    def get_generator_prompt(self, state: dict) -> list[dict]:
        """
        Build the Generator prompt for Content creation.
        """
        task = state.get("task_description", "")
        context = state.get("context", {})
        history = state.get("debate_history", [])
        iteration = state.get("iteration", 0)
        target_platform = context.get("platform", "all")

        # Get last critique if revising
        last_critique = ""
        if iteration > 0 and history:
            for msg in reversed(history):
                if msg.get("role") == "critic":
                    last_critique = msg["content"]
                    break

        if target_platform != "all" and target_platform in PLATFORM_SPECS:
            spec_info = get_platform_prompt(target_platform)
            system_prompt = (
                "You are the Content Generator — a master copywriter and social media strategist.\n\n"
                "Your job is to write top-tier, highly engaging social media content for a SPECIFIC platform, "
                "based on the TASK below. The task may be a direct instruction (e.g. \"announce X\", "
                "\"write a post about Y\") that already contains everything you need — in that case, just write "
                "the post directly. Only ask for more information if the task is genuinely too vague to act on "
                "at all (e.g. it names no topic, product, or subject whatsoever).\n\n"
                f"PLATFORM SPECIFICATION:\n{spec_info}\n\n"
                "RULES:\n"
                "- Write directly in the platform's native tone.\n"
                "- Stop the scroll with a strong opening line / hook.\n"
                "- Keep formatting clean with proper spacing.\n"
                "- Output ONLY the final ready-to-post copy — never a request for more information unless the task truly names no subject."
            )
        else:
            # Generate all 6 platform variants
            specs_summary = "\n".join(
                f"- {spec['name']} ({key}): max {spec['max_length']} chars | Tone: {spec['tone']}"
                for key, spec in PLATFORM_SPECS.items()
            )
            system_prompt = (
                "You are the Content Generator — a multi-platform content specialist.\n\n"
                "Your job is to turn the TASK below into 6 distinct, platform-optimized posts. The task may be "
                "a transcript/article to repurpose, OR a direct instruction (e.g. \"announce X\") that already "
                "contains everything you need — in that case, just write the posts directly. Only ask for more "
                "information if the task truly names no topic, product, or subject at all:\n"
                "1. X (Twitter) (key: twitter)\n"
                "2. LinkedIn (key: linkedin)\n"
                "3. Facebook (key: facebook)\n"
                "4. Instagram (key: instagram)\n"
                "5. Reddit (key: reddit)\n"
                "6. Discord (key: discord)\n\n"
                f"PLATFORM OVERVIEW:\n{specs_summary}\n\n"
                "CRITICAL REQUIREMENTS:\n"
                "- Each post MUST be tailored specifically to that platform's culture and constraints.\n"
                "- Do NOT duplicate the exact same text across platforms.\n"
                "- Output MUST be valid JSON with keys: twitter, linkedin, facebook, instagram, reddit, discord.\n"
                "- Each key's value should be the complete post text as a string, never a request for more information unless the task truly names no subject."
            )

        user_content = f"TASK:\n{task}\n\n"

        if context:
            context_str = "\n".join(f"- {k}: {v}" for k, v in context.items() if k not in ("platform", "selected_docs"))
            if context_str:
                user_content += f"ADDITIONAL CONTEXT:\n{context_str}\n\n"

        if last_critique:
            user_content += (
                f"⚠️ REVISION ROUND {iteration + 1}.\n"
                f"Address the following Critic feedback in your updated draft:\n{last_critique}\n\n"
            )

        user_content += "Draft the content now:"

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def get_critic_prompt(self, state: dict) -> list[dict]:
        """
        Build the Critic prompt for Content quality review.
        """
        draft = state.get("current_draft", "")
        task = state.get("task_description", "")
        context = state.get("context", {})
        target_platform = context.get("platform", "all")

        system_prompt = (
            "You are the Content Critic — a ruthlessly objective Chief Content Officer.\n\n"
            "Your task is to evaluate the drafted content across 5 critical dimensions:\n"
            "1. HOOK QUALITY (1-10): Will this stop the scroll in the first 2 seconds?\n"
            "2. PLATFORM FIT (1-10): Does it feel native to the platform's tone and formatting rules?\n"
            "3. VALUE DENSITY (1-10): Does every paragraph deliver clear value without fluff?\n"
            "4. AUTHENTICITY (1-10): Does it feel like a human leader wrote it, or generic AI?\n"
            "5. CALL TO ACTION (1-10): Is there a natural, low-friction next step for the reader?\n\n"
            "FORMAT YOUR RESPONSE AS:\n"
            "- Dimension breakdown and specific feedback\n"
            "- Key Strengths\n"
            "- Critical Weaknesses / Required Edits\n"
            "- End with: CONFIDENCE: X/100\n\n"
            "Scoring guideline: 85+ = Publish Ready. Below 85 = Needs Revision."
        )

        user_content = (
            f"ORIGINAL TASK / SOURCE:\n{task}\n\n"
            f"TARGET PLATFORM: {target_platform}\n\n"
            f"DRAFT TO CRITIQUE:\n{draft}\n\n"
            "Provide your comprehensive critique and ending CONFIDENCE score:"
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
