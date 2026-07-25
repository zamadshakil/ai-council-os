"""
Strategy Council — Market analysis, commercial strategy, and strategic planning.
"""

from __future__ import annotations
from src.core.council_base import BaseCouncil


class StrategyCouncil(BaseCouncil):
    """Strategy Council: multi-agent strategic decision analysis and planning."""

    council_name = "strategy"
    confidence_threshold = 85.0
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
            "You are the Strategy Generator — a Principal Strategy Consultant.\n\n"
            "Your goal is to construct actionable strategic plans, market analyses, and risk assessments.\n\n"
            "RULES:\n"
            "- Provide structured frameworks (SWOT, positioning, execution roadmap)\n"
            "- Highlight potential risks and mitigation strategies\n"
            "- Focus on high-impact ROI and clear priorities\n"
        )

        user_content = f"STRATEGIC QUESTION / TASK:\n{task}\n\n"
        if context:
            user_content += f"BUSINESS CONTEXT:\n{context}\n\n"
        if last_critique:
            user_content += f"REVISION FEEDBACK FROM CRITIC:\n{last_critique}\n\n"
        user_content += "Provide strategic analysis and plan:"

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def get_critic_prompt(self, state: dict) -> list[dict]:
        draft = state.get("current_draft", "")
        task = state.get("task_description", "")

        system_prompt = (
            "You are the Strategy Critic — a Managing Partner who stresses-tests strategic proposals.\n\n"
            "Identify flaws in logic, unrealistic assumptions, and missing risk factors.\n"
            "Provide rigorous feedback and end your response with: CONFIDENCE: X/100"
        )

        user_content = f"TASK:\n{task}\n\nSTRATEGIC DRAFT:\n{draft}\n\nProvide critique and CONFIDENCE score:"

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
