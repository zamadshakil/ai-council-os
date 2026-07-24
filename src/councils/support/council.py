"""
Support Council — Analyzes YouTube comments, drafts contextual replies.

This council:
1. Analyzes the YouTube comment intent.
2. Checks video context to ensure accurate replies.
3. Drafts a helpful, non-robotic reply.
4. Critiques the tone and helpfulness.
"""

from src.core.council_base import BaseCouncil

class SupportCouncil(BaseCouncil):
    """Support Council: handles customer/viewer interactions and comments."""

    council_name = "support"
    confidence_threshold = 85.0
    max_iterations = 2

    def get_generator_prompt(self, state: dict) -> list[dict]:
        task = state.get("task_description", "")
        context = state.get("context", {})
        
        system_prompt = (
            "You are the Support Generator — an expert community manager.\n\n"
            "Your job is to reply to YouTube comments thoughtfully and accurately.\n\n"
            "RULES:\n"
            "- Be concise and helpful.\n"
            "- Do not sound like a bot. Speak in a natural, friendly tone.\n"
            "- Address the specific question or sentiment in the comment.\n"
        )
        
        user_content = f"TASK:\n{task}\n\nCOMMENT CONTEXT:\n{context}\n\nWrite the reply:"
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def get_critic_prompt(self, state: dict) -> list[dict]:
        draft = state.get("current_draft", "")
        task = state.get("task_description", "")
        
        system_prompt = (
            "You are the Support Critic.\n\n"
            "Evaluate the draft reply for Tone, Helpfulness, and Authenticity (not robotic).\n"
            "Format your response with feedback and end with CONFIDENCE: X/100."
        )
        
        user_content = f"ORIGINAL TASK:\n{task}\n\nDRAFT:\n{draft}\n\nProvide critique and CONFIDENCE score:"
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
