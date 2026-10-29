"""Minimal embedded LLM client for comment summarization.

Talks to any OpenAI-compatible /chat/completions endpoint using only
`requests` (no SDK dependency). Works with OpenAI, OpenRouter, LM Studio,
vLLM and Ollama.
"""

import json
import os
import re
import time

import requests

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

ENV_BASE_URL = "GH_ISSUE_LENS_LLM_BASE_URL"
ENV_API_KEY = "GH_ISSUE_LENS_LLM_API_KEY"
ENV_MODEL = "GH_ISSUE_LENS_LLM_MODEL"

ENV_PROVIDER = "GH_ISSUE_LENS_LLM_PROVIDER"
PROVIDER_PRESETS = {
    "nvidia": ("https://integrate.api.nvidia.com/v1", "nvidia/nemotron-3.5-lightning-30b-a3b"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "ollama": ("http://127.0.0.1:11434/v1", "llama3.2"),
}

# Safety net for pathological single comments (LLM *input* only,
# the export itself is never character-truncated).
INPUT_COMMENT_CAP = 20000

MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 5


def load_dotenv(path=".env"):
    """Minimal .env loader (no new dependency). Real env vars take precedence."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass


class LLMError(Exception):
    """Raised when the LLM endpoint cannot produce a summary."""


def extract_json(text):
    """Extract a JSON object from LLM text output, stripping markdown blocks."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


class LLMClient:
    """Small OpenAI-compatible chat client used to summarize comment threads."""

    def __init__(self, base_url=None, api_key=None, model=None, timeout=120):
        load_dotenv()
        preset = PROVIDER_PRESETS.get((os.getenv(ENV_PROVIDER) or "").lower())
        preset_base, preset_model = preset if preset else (None, None)
        self.base_url = (
            base_url or os.getenv(ENV_BASE_URL) or preset_base or DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv(ENV_API_KEY)
        self.model = model or os.getenv(ENV_MODEL) or preset_model or DEFAULT_MODEL
        self.timeout = timeout

    def describe(self):
        masked = "set" if self.api_key else "not set"
        return f"{self.base_url} (model={self.model}, api_key={masked})"

    def summarize_comments(self, issue_number, title, comments, total_comment_count=None):
        """Return a compact factual summary of an issue's comment thread."""
        if not comments:
            return "No comments yet."

        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You summarize GitHub issue comment threads for newcomers. "
                        "Be factual, concise and never invent information that is not "
                        "present in the comments."
                    ),
                },
                {
                    "role": "user",
                    "content": build_prompt(issue_number, title, comments, total_comment_count),
                },
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                last_error = f"network error: {exc}"
            else:
                if response.status_code == 200:
                    try:
                        data = response.json()
                        text = data["choices"][0]["message"]["content"].strip()
                        if text:
                            return text
                        last_error = "empty completion"
                    except (ValueError, KeyError, IndexError) as exc:
                        last_error = f"unexpected response shape: {exc}"
                else:
                    last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                    # Only retry on transient failures.
                    if response.status_code not in (408, 429, 500, 502, 503, 504):
                        break
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))

        raise LLMError(last_error or "unknown error")

    def score_difficulty(self, title, body, labels):
        """Return a difficulty score (1-5) and reason for a single issue."""
        body_capped = (body or "")[:4000]  # Cap to avoid token limits
        prompt = (
            f"Issue Title: {title}\n"
            f"Labels: {', '.join(labels) if labels else 'None'}\n"
            f"Issue Body:\n{body_capped}\n\n"
            "Act as a senior open source maintainer evaluating this issue for a beginner. "
            "Rate the difficulty of this issue on a scale of 1 to 5, where:\n"
            "1 = Trivial (typos, simple docs, config tweaks)\n"
            "2 = Easy (small bug fixes, adding simple tests, minor refactors)\n"
            "3 = Moderate (requires understanding of specific modules, standard features)\n"
            "4 = Hard (complex logic, architectural changes, deep domain knowledge)\n"
            "5 = Expert (core rewrites, complex debugging, cross-system impacts)\n\n"
            "You MUST respond with ONLY a valid JSON object in this exact format, with no markdown formatting or extra text:\n"
            '{"score": <integer 1-5>, "reason": "<short explanation max 20 words>"}'
        )

        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert open source maintainer. You output ONLY valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                last_error = f"network error: {exc}"
            else:
                if response.status_code == 200:
                    try:
                        data = response.json()
                        text = data["choices"][0]["message"]["content"].strip()
                        parsed = extract_json(text)
                        if parsed and "score" in parsed:
                            return parsed
                        last_error = "failed to parse JSON or missing 'score' key"
                    except (ValueError, KeyError, IndexError) as exc:
                        last_error = f"unexpected response shape: {exc}"
                else:
                    last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                    if response.status_code not in (408, 429, 500, 502, 503, 504):
                        break
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))

        raise LLMError(last_error or "unknown error")


def build_prompt(issue_number, title, comments, total_comment_count=None):
    """Build the user prompt from an issue's comment thread."""
    lines = [
        f"GitHub issue #{issue_number}: {title}",
        "",
        "Comment thread (format: [n] author: body):",
        "",
    ]
    for index, comment in enumerate(comments, 1):
        body = (comment.get("body") or "").strip()
        if len(body) > INPUT_COMMENT_CAP:
            body = body[:INPUT_COMMENT_CAP] + " [...input capped for the LLM]"
        author = comment.get("author") or "unknown"
        lines.append(f"[{index}] {author}: {body}")
        lines.append("")

    if total_comment_count and total_comment_count > len(comments):
        lines.append(
            f"Note: only the first {len(comments)} of {total_comment_count} total "
            "comments are shown."
        )
        lines.append("")

    lines.append(
        "Write one factual summary paragraph (max ~120 words) covering: "
        "the current consensus or decision, maintainer feedback, blockers, "
        "any proposed solutions, and whether the issue still looks open for a newcomer."
    )
    return "\n".join(lines)
