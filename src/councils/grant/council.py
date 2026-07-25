"""
Grant Council — Proposal writing, technical methodology, and compliance review.
"""

from __future__ import annotations
from src.core.council_base import BaseCouncil


class GrantCouncil(BaseCouncil):
    """Grant Council: multi-agent grant application and proposal generator."""

    council_name = "grant"
    confidence_threshold = 88.0
    max_iterations = 3

    def get_generator_prompt(self, state: dict) -> list[dict]:
        task = state.get("task_description", "")
        context = state.get("context", {})
        history = state.get("debate_history", [])
        iteration = state.get("iteration", 0)

        last_critique = ""
        if iteration > 0 and history:
            for msg in reversed(history):
                if msg.get("role") == "critic":
                    last_critique = msg["content"]
                    break

        system_prompt = (
            "You are the Grant Generator — an expert grant writer and technical proposal author.\n\n"
            "Your goal is to draft structured, highly persuasive grant application sections.\n\n"
            "RULES:\n"
            "- Rigorously align with evaluation criteria and problem statements\n"
            "- Include technical methodology, impact metrics, and budget rationale\n"
            "- Maintain an academic yet highly convincing tone\n"
        )

        user_content = f"GRANT TASK / CALL:\n{task}\n\n"
        if context:
            user_content += f"CONTEXT:\n{context}\n\n"
        if last_critique:
            user_content += f"CRITIQUE FEEDBACK TO REVISE:\n{last_critique}\n\n"
        user_content += "Draft the grant proposal section:"

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def get_critic_prompt(self, state: dict) -> list[dict]:
        draft = state.get("current_draft", "")
        task = state.get("task_description", "")

        system_prompt = (
            "You are the Grant Critic — a veteran reviewer for grant evaluation panels.\n\n"
            "Evaluate the proposal draft against evaluation criteria, feasibility, and impact.\n"
            "Provide detailed feedback and end your response with: CONFIDENCE: X/100"
        )

        user_content = f"ORIGINAL TASK:\n{task}\n\nDRAFT:\n{draft}\n\nProvide critique and CONFIDENCE score:"

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
