#!/usr/bin/env python3
"""Generate an MDX tutorial page with LLM-authored step summaries."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    from writerai import Writer
except ModuleNotFoundError:  # pragma: no cover
    Writer = None  # type: ignore[assignment]

try:
    import dotenv
except ModuleNotFoundError:  # pragma: no cover
    dotenv = None  # type: ignore[assignment]

if dotenv is not None:
    dotenv.load_dotenv()


@dataclass
class StepContext:
    index: int
    title_hint: str
    start_time: float
    end_time: Optional[float]
    showcase_time: Optional[float]
    screenshot: Optional[Path]
    transcript_text: str


class Summarizer:
    def summarize(self, *, tutorial_title: str, step: StepContext) -> str:
        raise NotImplementedError


class MockSummarizer(Summarizer):
    def __init__(self, max_chars: int = 320) -> None:
        self._max_chars = max_chars

    def summarize(self, *, tutorial_title: str, step: StepContext) -> str:
        base = step.transcript_text.strip() or step.title_hint.strip()
        if not base:
            return "Instruction unavailable."
        return (base[: self._max_chars] + "…") if len(base) > self._max_chars else base


class WriterSummarizer(Summarizer):
    def __init__(
        self,
        *,
        api_key: Optional[str],
        model: str,
        temperature: float,
        system_prompt: str,
    ) -> None:
        if Writer is None:
            raise RuntimeError(
                "The 'writerai' package is required for the Writer provider. Install it via `pip install writerai`."
            )
        self._client = Writer(api_key=api_key) if api_key else Writer()
        self._model = model
        self._temperature = temperature
        self._system_prompt = system_prompt

    def summarize(self, *, tutorial_title: str, step: StepContext) -> str:
        prompt = build_prompt(tutorial_title=tutorial_title, step=step)
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": prompt},
        ]
        with self._client.chat.stream(
            messages=messages,
            model=self._model,
            temperature=self._temperature,
        ) as stream:
            for event in stream:
                # Drain the stream without emitting incremental tokens.
                if getattr(event, "type", None) == "content.delta":
                    continue
            completion = stream.get_final_completion()

        try:
            content = completion.choices[0].message.content
        except (AttributeError, IndexError, KeyError) as exc:  # pragma: no cover
            raise RuntimeError("Unexpected response from Writer API") from exc

        if isinstance(content, list):  # Writer SDK may return rich content
            text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            text = "".join(text_parts)
        else:
            text = str(content)

        cleaned = text.strip()
        return cleaned if cleaned else "Instruction unavailable."



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a tutorial JSON export into an MDX walkthrough with LLM summaries.",
    )
    parser.add_argument(
        "input", type=Path, help="Path to the JSON file that lists tutorial steps."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Optional MDX output path. Defaults to swapping the input extension to .mdx",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include steps even if they are flagged as not relevant.",
    )
    parser.add_argument(
        "--transcript-dir",
        type=Path,
        help="Override the directory containing full transcripts (defaults to ../transcripts).",
    )
    parser.add_argument(
        "--context-padding",
        type=float,
        default=1.0,
        help="Seconds of transcript context to include before and after each step window.",
    )
    parser.add_argument(
        "--llm-provider",
        choices=("writer", "mock"),
        default="writer",
        help="Which summarisation backend to use.",
    )
    parser.add_argument(
        "--writer-model",
        default="palmyra-x5",
        help="Model identifier to request from the Writer API.",
    )
    parser.add_argument(
        "--writer-api-key",
        help="API key for Writer. Falls back to the WRITER_API_KEY environment variable.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.3,
        help="Sampling temperature for the LLM provider.",
    )
    parser.add_argument(
        "--writer-system-prompt",
        default=(
            "You are an expert GIMP instructor. Write concise, friendly step summaries with clear actions,"
            " focusing on what the learner should do and notice. Avoid emojis and filler text."
        ),
        help="Override the system prompt supplied to the Writer chat model.",
    )
    parser.add_argument(
        "--mock-max-chars",
        type=int,
        default=320,
        help="Maximum characters returned by the mock provider (testing aid).",
    )
    return parser.parse_args()


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def derive_title(payload: Dict[str, Any]) -> str:
    video_name = payload.get("video")
    if not video_name:
        return "Tutorial"
    stem = Path(str(video_name)).stem
    return stem.replace("_", " ")


def format_timestamp(value: Optional[float]) -> str:
    if value is None:
        return ""
    total_seconds = max(0, int(round(float(value))))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


def resolve_transcript_path(input_path: Path, override_dir: Optional[Path]) -> Path:
    if override_dir:
        return override_dir / input_path.name
    return input_path.parent.parent / "transcripts" / input_path.name


def extract_transcript_words(
    transcript_payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
    channels = transcript_payload.get("results", {}).get("channels", [])
    if not channels:
        return []
    alternatives = channels[0].get("alternatives", [])
    if not alternatives:
        return []
    return alternatives[0].get("words", [])


def transcript_duration(transcript_payload: Dict[str, Any]) -> Optional[float]:
    metadata = transcript_payload.get("metadata", {})
    duration = metadata.get("duration")
    return float(duration) if duration is not None else None


def slice_transcript(
    words: Iterable[Dict[str, Any]],
    start: float,
    end: Optional[float],
) -> str:
    tokens: List[str] = []
    for word in words:
        try:
            word_start = float(word.get("start", 0.0))
        except (TypeError, ValueError):
            continue
        if word_start < start:
            continue
        if end is not None and word_start >= end:
            break
        text = word.get("punctuated_word") or word.get("word")
        if text:
            tokens.append(str(text))
    joined = " ".join(tokens)
    return tidy_spacing(joined)


def tidy_spacing(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    return text


def build_prompt(*, tutorial_title: str, step: StepContext) -> str:
    start_label = format_timestamp(step.start_time)
    end_label = format_timestamp(step.end_time)
    showcase_label = format_timestamp(step.showcase_time)
    context = step.transcript_text or step.title_hint
    instructions = (
        "You are helping produce a concise, action-focused GIMP tutorial. "
        "Write 2-4 sentences that describe the essential actions and reasoning for this step. "
        "Highlight tool names, parameter changes, or visual cues the learner should watch. "
        "Avoid filler, keep the voice instructional, and do not mention transcript or timing metadata."
    )
    return (
        f"Tutorial: {tutorial_title}\n"
        f"Step: {step.index}\n"
        f"Cue: {step.title_hint}\n"
        f"Window: starts {start_label or '0:00'}"
        f"{f', ends {end_label}' if end_label else ''}"
        f"{f', showcase {showcase_label}' if showcase_label else ''}\n\n"
        f"{instructions}\n\n"
        f"Transcript excerpt:\n"
        f"""""{context}"""
        "\n"
        "Response:"
    )


def ensure_output_path(input_path: Path, override: Optional[Path]) -> Path:
    return override if override else input_path.with_suffix(".mdx")


def resolve_screenshot(
    step: Dict[str, Any], input_path: Path, output_path: Path
) -> Optional[Path]:
    screenshot_value = step.get("screenshot")
    if not screenshot_value:
        return None
    base_dir = input_path.parent.parent
    screenshot_path = Path(screenshot_value)
    if not screenshot_path.is_absolute():
        screenshot_path = base_dir / screenshot_path
    if not screenshot_path.exists():
        return None
    rel = os.path.relpath(screenshot_path, output_path.parent)
    return Path(rel)


def build_step_contexts(
    *,
    payload: Dict[str, Any],
    include_all: bool,
    input_path: Path,
    output_path: Path,
    transcript_words: List[Dict[str, Any]],
    duration: Optional[float],
    context_padding: float,
) -> List[StepContext]:
    raw_steps = payload.get("steps", [])
    sorted_steps = sorted(
        raw_steps,
        key=lambda item: float(item.get("start_time") or 0.0),
    )
    contexts: List[StepContext] = []
    for idx, step in enumerate(sorted_steps):
        if not include_all and not step.get("is_relevant", True):
            continue
        start_time = float(step.get("start_time") or 0.0)
        next_start = None
        for future in sorted_steps[idx + 1 :]:
            candidate_start = future.get("start_time")
            if candidate_start is not None:
                next_start = float(candidate_start)
                break
        end_time = next_start if next_start is not None else duration
        window_start = max(0.0, start_time - context_padding)
        window_end = (end_time + context_padding) if end_time is not None else None
        transcript_excerpt = slice_transcript(
            transcript_words,
            window_start,
            window_end,
        )
        title_hint = (step.get("title_hint") or "").strip() or "Step details"
        screenshot = resolve_screenshot(step, input_path, output_path)
        contexts.append(
            StepContext(
                index=int(step.get("index") or len(contexts) + 1),
                title_hint=title_hint,
                start_time=start_time,
                end_time=end_time,
                showcase_time=(
                    float(step.get("showcase_frame_time"))
                    if step.get("showcase_frame_time") is not None
                    else None
                ),
                screenshot=screenshot,
                transcript_text=transcript_excerpt,
            )
        )
    return contexts


def render_mdx_document(
    *,
    title: str,
    steps: List[StepContext],
    summaries: Dict[int, str],
) -> str:
    timestamp = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    safe_title = title.replace('"', '\\"')
    lines: List[str] = [
        "---",
        f'title: "{safe_title}"',
        f'generatedAt: "{timestamp}"',
        "---",
        "",
    ]
    lines.append(f"# {title}")
    lines.append("")
    for step in steps:
        summary = summaries.get(step.index, "")
        heading = f"## Step {step.index}: {step.title_hint}"
        lines.append(heading)
        timing_bits: List[str] = []
        start_label = format_timestamp(step.start_time)
        if start_label:
            timing_bits.append(f"starts {start_label}")
        if step.showcase_time is not None:
            showcase_label = format_timestamp(step.showcase_time)
            if showcase_label:
                timing_bits.append(f"showcase {showcase_label}")
        if step.end_time is not None:
            end_label = format_timestamp(step.end_time)
            if end_label:
                timing_bits.append(f"ends {end_label}")
        if timing_bits:
            lines.append(f"*{', '.join(timing_bits)}*")
            lines.append("")
        if step.screenshot is not None:
            lines.append(
                f"![Step {step.index} screenshot]({step.screenshot.as_posix()})"
            )
            lines.append("")
        if summary:
            lines.append(summary.strip())
            lines.append("")
        else:
            lines.append("Instruction unavailable.")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def select_summarizer(args: argparse.Namespace) -> Summarizer:
    if args.llm_provider == "mock":
        return MockSummarizer(max_chars=args.mock_max_chars)
    api_key = args.writer_api_key or os.environ.get("WRITER_API_KEY")
    return WriterSummarizer(
        api_key=api_key,
        model=args.writer_model,
        temperature=args.temperature,
        system_prompt=args.writer_system_prompt,
    )


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    payload = load_json(input_path)
    title = derive_title(payload)
    output_path = ensure_output_path(input_path, args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    transcript_path = resolve_transcript_path(input_path, args.transcript_dir)
    if not transcript_path.exists():
        raise SystemExit(f"Transcript file not found: {transcript_path}")
    transcript_payload = load_json(transcript_path)
    words = extract_transcript_words(transcript_payload)
    duration = transcript_duration(transcript_payload)

    step_contexts = build_step_contexts(
        payload=payload,
        include_all=args.include_all,
        input_path=input_path,
        output_path=output_path,
        transcript_words=words,
        duration=duration,
        context_padding=max(0.0, args.context_padding),
    )
    if not step_contexts:
        raise SystemExit(
            "No steps available to render. Use --include-all to include filtered steps."
        )

    summarizer = select_summarizer(args)
    summaries: Dict[int, str] = {}
    for step in step_contexts:
        try:
            summaries[step.index] = summarizer.summarize(
                tutorial_title=title,
                step=step,
            )
        except Exception as exc:  # pragma: no cover
            summaries[step.index] = f"Instruction unavailable ({exc})."

    document = render_mdx_document(
        title=title, steps=step_contexts, summaries=summaries
    )
    with output_path.open("w", encoding="utf-8") as fh:
        fh.write(document)

    print(f"Tutorial MDX written to {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
