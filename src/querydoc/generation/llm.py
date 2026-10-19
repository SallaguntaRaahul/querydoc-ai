"""Local Hugging Face causal-LM wrapper. The model is loaded once and reused;
generation calls are serialised because one model instance cannot safely run
several ``generate`` calls at the same time on MPS/CPU."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

from querydoc.config import resolve_device
from querydoc.exceptions import GenerationError, GenerationUnavailableError
from querydoc.logging_utils import get_logger, kv

log = get_logger(__name__)


@dataclass
class GenerationParams:
    max_new_tokens: int = 256
    temperature: float = 0.0
    top_p: float = 0.9
    repetition_penalty: float = 1.05


@dataclass
class GenerationResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    time_to_first_token_ms: float

    @property
    def tokens_per_second(self) -> float:
        return self.completion_tokens / (self.latency_ms / 1000) if self.latency_ms > 0 else 0.0


def _is_oom(exc: BaseException) -> bool:
    return "out of memory" in str(exc).lower() or type(exc).__name__ == "OutOfMemoryError"


class LocalLLM:
    def __init__(self, model_name: str, *, device: str = "auto", local_files_only: bool = False) -> None:
        self.model_name = model_name
        self.device = resolve_device(device)
        self._lock = threading.Lock()
        started = time.perf_counter()
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            dtype = torch.float16 if self.device in {"cuda", "mps"} else torch.float32
            self.tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=local_files_only)
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name, dtype=dtype, local_files_only=local_files_only
            ).to(self.device)
            self.model.eval()
            self.revision = getattr(self.model.config, "_commit_hash", None)
        except Exception as exc:
            raise GenerationUnavailableError(
                f"Could not load local model '{model_name}' on {self.device}: {exc}"
            ) from exc
        self.load_seconds = time.perf_counter() - started
        log.info(kv("llm_loaded", model=model_name, device=self.device, seconds=self.load_seconds))

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def _inputs(self, messages: list[dict[str, str]]):  # type: ignore[no-untyped-def]
        prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        return self.tokenizer(prompt, return_tensors="pt").to(self.device)

    def stream(self, messages: list[dict[str, str]], params: GenerationParams) -> Iterator[str]:
        """Yield text fragments as they are generated."""
        from transformers import TextIteratorStreamer

        inputs = self._inputs(messages)
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=params.max_new_tokens,
            repetition_penalty=params.repetition_penalty,
            pad_token_id=self.tokenizer.eos_token_id,
        )
        if params.temperature > 0:
            kwargs.update(do_sample=True, temperature=params.temperature, top_p=params.top_p)
        else:
            kwargs.update(do_sample=False, temperature=None, top_p=None, top_k=None)

        error: list[BaseException] = []

        def run() -> None:
            import torch

            try:
                with torch.inference_mode():
                    self.model.generate(**kwargs)
            except BaseException as exc:  # surfaced to the consumer below
                error.append(exc)
                streamer.end()

        with self._lock:
            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            yield from streamer
            worker.join()
        if error:
            exc = error[0]
            if _is_oom(exc):
                self._free_memory()
                raise GenerationError(
                    "The local model ran out of memory. Reduce top-k, context length or max tokens."
                ) from exc
            raise GenerationError(f"Generation failed: {exc}") from exc

    def generate(self, messages: list[dict[str, str]], params: GenerationParams | None = None) -> GenerationResult:
        params = params or GenerationParams()
        prompt_tokens = int(self._inputs(messages)["input_ids"].shape[1])
        started = time.perf_counter()
        first: float | None = None
        parts: list[str] = []
        for piece in self.stream(messages, params):
            if first is None and piece:
                first = time.perf_counter()
            parts.append(piece)
        latency = (time.perf_counter() - started) * 1000
        text = "".join(parts).strip()
        return GenerationResult(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=self.count_tokens(text),
            latency_ms=latency,
            time_to_first_token_ms=((first or time.perf_counter()) - started) * 1000,
        )

    def _free_memory(self) -> None:
        try:
            import torch

            if self.device == "cuda":
                torch.cuda.empty_cache()
            elif self.device == "mps":
                torch.mps.empty_cache()
        except Exception:
            pass
