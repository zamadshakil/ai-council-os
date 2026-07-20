"""
Sales Council — Lead qualification, outreach strategy, and email generation.

This council:
1. Researches the lead/company
2. Analyzes buying signals and fit
3. Drafts personalized outreach
4. Critiques the outreach for quality
5. Submits for human approval before sending

The debate ensures outreach is never generic — every email is
reviewed by the Critic for personalization quality, tone, and strategy.
"""

from __future__ import annotations

from src.core.council_base import BaseCouncil
from src.core.memory import get_relevant_guidelines


class SalesCouncil(BaseCouncil):
    """Sales Council: multi-agent outreach generation with debate."""

    council_name = "sales"
    confidence_threshold = 85.0
    max_iterations = 3

    def get_generator_prompt(self, state: dict) -> list[dict]:
        """
        Build the Generator prompt for sales outreach.

        The Generator receives:
        - The task description (lead info, what to do)
        - Any context (company data, LinkedIn profile, etc.)
        - Past feedback guidelines (learned from human edits)
        - Previous critique (if this is a revision round)
        """
        task = state.get("task_description", "")
        context = state.get("context", {})
        history = state.get("debate_history", [])
        iteration = state.get("iteration", 0)

        # Build context section
        context_text = ""
        if context:
            context_text = "\n".join(
                f"- {k}: {v}" for k, v in context.items()
            )

        # Get last critique if this is a revision
        last_critique = ""
        if iteration > 0 and history:
            for msg in reversed(history):
                if msg.get("role") == "critic":
                    last_critique = msg["content"]
                    break

        system_prompt = (
            "You are the Sales Generator — an expert B2B outreach specialist.\n\n"
            "Your job is to craft highly personalized, compelling outreach messages "
            "that feel human-written, not templated.\n\n"
            "RULES:\n"
            "- Reference specific details about the prospect's company/role\n"
            "- Lead with value, not a pitch\n"
            "- Keep it under 150 words\n"
            "- No generic openings like 'I hope this finds you well'\n"
            "- Include a clear, low-friction CTA\n"
        )

        user_content = f"TASK:\n{task}\n\n"

        if context_text:
            user_content += f"PROSPECT CONTEXT:\n{context_text}\n\n"

        if last_critique:
            user_content += (
                f"⚠️ REVISION ROUND {iteration + 1}. "
                f"Address this critique:\n{last_critique}\n\n"
            )

        user_content += "Write the outreach message:"

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def get_critic_prompt(self, state: dict) -> list[dict]:
        """
        Build the Critic prompt for sales outreach review.

        The Critic evaluates:
        - Personalization (does it reference real prospect details?)
        - Value proposition (is the benefit clear?)
        - Tone (professional but human?)
        - CTA quality (clear, low-friction?)
        - Length (under 150 words?)

        Must output a CONFIDENCE score at the end.
        """
        draft = state.get("current_draft", "")
        task = state.get("task_description", "")
        context = state.get("context", {})

        context_text = ""
        if context:
            context_text = "\n".join(
                f"- {k}: {v}" for k, v in context.items()
            )

        system_prompt = (
            "You are the Sales Critic — a senior sales strategist who reviews outreach.\n\n"
            "Your job is to ruthlessly evaluate the draft outreach message.\n\n"
            "EVALUATE ON THESE CRITERIA (score each 1-10):\n"
            "1. PERSONALIZATION: Does it reference specific prospect details?\n"
            "2. VALUE PROP: Is the benefit to the prospect crystal clear?\n"
            "3. TONE: Professional but human? Not salesy or robotic?\n"
            "4. CTA: Clear, specific, low-friction call to action?\n"
            "5. LENGTH: Concise? Under 150 words?\n\n"
            "FORMAT YOUR RESPONSE AS:\n"
            "- Per-criteria scores and specific feedback\n"
            "- What's working well\n"
            "- What needs improvement (be specific)\n"
            "- End with: CONFIDENCE: X/100\n\n"
            "Score 85+ means ready to send. Below 85 means it needs revision.\n"
            "Be tough but fair. Generic outreach should score below 60."
        )

        user_content = (
            f"ORIGINAL TASK:\n{task}\n\n"
        )

        if context_text:
            user_content += f"PROSPECT CONTEXT:\n{context_text}\n\n"

        user_content += f"DRAFT TO REVIEW:\n{draft}\n\nProvide your critique and CONFIDENCE score:"

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
