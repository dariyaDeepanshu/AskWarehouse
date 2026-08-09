"""Local, free, no-API-key model provider. Runs Qwen2.5-Coder-7B-Instruct
4-bit (bitsandbytes) on-GPU via transformers. This is the default provider
for AskWarehouse specifically because there is no API key in this
environment -- everything downstream (schema retrieval doesn't need an LLM,
but ambiguity check / planning / SQL generation / self-critique / NL answer
all do) has to work without one.

The model is loaded lazily and once per process (module-level singleton) --
importing this module does not touch the GPU; the first call to generate()
does, and every call after that reuses the loaded weights.
"""
import time
import threading

from askwarehouse.providers.base import Provider, LLMResponse

MODEL_ID = "Qwen/Qwen2.5-Coder-7B-Instruct"

_lock = threading.Lock()
_model = None
_tokenizer = None


def _ensure_loaded():
    global _model, _tokenizer
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID,
            quantization_config=bnb_config,
            device_map="auto",
        )
        model.eval()
        _tokenizer = tokenizer
        _model = model


class LocalProvider(Provider):
    name = "local:qwen2.5-coder-7b-instruct-4bit"

    def __init__(self, model_id: str = MODEL_ID):
        self.model_id = model_id

    def generate(self, system: str, user: str, max_tokens: int = 800,
                 temperature: float = 0.0) -> LLMResponse:
        import torch

        _ensure_loaded()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        prompt_text = _tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = _tokenizer([prompt_text], return_tensors="pt").to(_model.device)

        t0 = time.perf_counter()
        with torch.no_grad():
            output_ids = _model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=temperature > 0,
                temperature=max(temperature, 1e-5) if temperature > 0 else None,
                pad_token_id=_tokenizer.eos_token_id,
            )
        latency_ms = (time.perf_counter() - t0) * 1000

        completion_ids = output_ids[0][inputs.input_ids.shape[1]:]
        text = _tokenizer.decode(completion_ids, skip_special_tokens=True)

        return LLMResponse(
            text=text.strip(),
            prompt_tokens=int(inputs.input_ids.shape[1]),
            completion_tokens=int(completion_ids.shape[0]),
            latency_ms=latency_ms,
            provider="local",
            model=self.model_id,
        )


def is_model_cached() -> bool:
    """Cheap check used by the CLI/UI to warn the user before the first
    (slow) call triggers a download+load."""
    from huggingface_hub import scan_cache_dir
    try:
        cache = scan_cache_dir()
        return any(MODEL_ID in repo.repo_id for repo in cache.repos)
    except Exception:
        return False
