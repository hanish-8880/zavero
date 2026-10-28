"""Responses API computer-use loop. Asks the model for the next step, one screenshot at a time."""
from dataclasses import dataclass, field

from openai import APIConnectionError, APIStatusError, APITimeoutError

from zavero import config
from zavero.driver import Shot

SYSTEM = """You help a beginner on an Indian user's Windows computer.
Sometimes the user performs your actions themselves, so always check the new screenshot to see what really happened.
- Click the center of target elements.
- Batch actions only when they don't depend on a new screenshot. Never batch across page loads or dialogs. Use wait while loading.
- Never type passwords, OTPs, card numbers, Aadhaar or PAN. If needed, stop and ask the user to type them.
- Never press Pay / Submit / Send / Delete / Confirm without the user's explicit approval.
- With every step, write one short English sentence naming the exact on-screen label in double quotes, e.g. I'll click "Quick Pay".
- If this click would pay money, submit a form, send a message, delete something, place an order or confirm something final, start that sentence with "APPROVAL NEEDED:". Opening a page or menu is not final.
- Do only what the user asked. If it is already done on screen, just say so and finish. Never invent extra work.
- Find things yourself instead of asking: e.g. open Chrome and search Google for the official website. Ask the user only for what only they know (like their service number), and only when you reach the box that needs it.
- The request may include earlier conversation. Use it: the user's latest words often answer your earlier question.
- Finish with a short message when the goal is visibly complete, or explain clearly why it can't be done.
- Do not claim completion unless the screenshot shows it."""

TOOLS = [{"type": "computer"}]


@dataclass
class Step:
    """One computer_call from the model."""
    call_id: str
    actions: list
    safety_checks: list = field(default_factory=list)  # [{id, code, message}]
    text: str = ""  # the model's English note for this step


class Brain:
    """Holds one task's conversation with the model."""

    def __init__(self, task: str, model: str = config.MODEL_SPARK):
        self.task = task
        self.model = model
        self.client = config.client()
        self.prev_id: str | None = None
        self.steps = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def start(self, shot: Shot) -> "Step | str":
        """First turn: task + screenshot. Returns a Step, or the final text."""
        return self._call([{
            "role": "user",
            "content": [
                {"type": "input_text", "text": self.task},
                {"type": "input_image", "image_url": shot.data_url},
            ],
        }])

    def next(self, step: Step, shot: Shot, acknowledged: list | None = None) -> "Step | str":
        """Send the screenshot after a step. Only pass safety checks the user approved."""
        return self._call([{
            "type": "computer_call_output",
            "call_id": step.call_id,
            "acknowledged_safety_checks": acknowledged or [],
            "output": {"type": "computer_screenshot", "image_url": shot.data_url},
        }])

    def _call(self, input_items: list) -> "Step | str":
        self.steps += 1
        kwargs = {"previous_response_id": self.prev_id} if self.prev_id else {}
        last_err = None
        for _ in range(2):  # one retry on network/server trouble
            try:
                resp = self.client.responses.create(
                    model=self.model, instructions=SYSTEM, tools=TOOLS,
                    input=input_items, truncation="auto", **kwargs,
                )
                break
            except APIStatusError as e:
                last_err = f"API error {e.status_code}: {e.message}"
                if e.status_code < 500:
                    raise RuntimeError(last_err) from e
            except (APITimeoutError, APIConnectionError) as e:
                last_err = f"Network problem: {e}"
        else:
            raise RuntimeError(last_err)

        self.prev_id = resp.id
        if resp.usage:
            self.tokens_in += resp.usage.input_tokens
            self.tokens_out += resp.usage.output_tokens
        text = (resp.output_text or "").strip()
        calls = [o for o in resp.output if o.type == "computer_call"]
        if not calls:
            return text or "Done."
        call = calls[0]
        checks = [
            {"id": c.id, "code": c.code, "message": c.message}
            for c in (call.pending_safety_checks or [])
        ]
        return Step(call.call_id, list(call.actions), checks, text)
