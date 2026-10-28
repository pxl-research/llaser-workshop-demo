"""NLP prompt defense: a DistilBERT classifier exported to ONNX."""

import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

logger = logging.getLogger(__name__)

MODEL_PATH = "/app/AI/API/models/malicious_prompt_detector"


class MLPromptSafetyDetector:
    REQUIRED_FILES = ("model.onnx", "tokenizer.json")

    def __init__(self, model_path=MODEL_PATH, confidence_threshold: float = 0.5):
        self.model_path = Path(model_path)
        self.confidence_threshold = confidence_threshold
        self.session = None
        self.tokenizer = None
        self.is_loaded = False
        self.load_error: str | None = None
        self.load_model()

    def load_model(self):
        """Load tokenizer and model from disk."""
        if not all((self.model_path / name).is_file() for name in self.REQUIRED_FILES):
            self.load_error = (
                f"NLP defense model not found at {self.model_path}. "
                "Run docker compose logs model-init and see the README."
            )
            logger.warning(self.load_error)
            return

        try:
            self.tokenizer = Tokenizer.from_file(str(self.model_path / "tokenizer.json"))
            self.tokenizer.enable_truncation(max_length=256)
            self.session = ort.InferenceSession(
                str(self.model_path / "model.onnx"), providers=["CPUExecutionProvider"]
            )
            self.is_loaded = True
            logger.info("NLP defense model loaded from %s", self.model_path)
        except Exception as e:
            self.load_error = f"Failed to load NLP defense model from {self.model_path}: {e}"
            logger.exception("Loading the NLP defense model failed")

    def detect(self, prompt: str) -> dict:
        """Classify one prompt; only call when is_loaded."""
        enc = self.tokenizer.encode(prompt)
        feeds = {
            "input_ids": np.array([enc.ids], dtype=np.int64),
            "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
        }
        logits = self.session.run(None, feeds)[0][0]
        probs = np.exp(logits - logits.max())
        probs /= probs.sum()
        # Label 0 is benign, 1 is malicious.
        benign_prob, malicious_prob = float(probs[0]), float(probs[1])
        return {
            "is_malicious": malicious_prob >= self.confidence_threshold,
            "confidence": max(benign_prob, malicious_prob),
            "risk_level": risk_level(malicious_prob),
        }

    def set_threshold(self, threshold: float):
        if not 0 <= threshold <= 1:
            raise ValueError("Threshold must be between 0 and 1")
        self.confidence_threshold = threshold


def risk_level(malicious_probability: float) -> str:
    if malicious_probability < 0.25:
        return "Low"
    if malicious_probability < 0.50:
        return "Medium"
    if malicious_probability < 0.75:
        return "High"
    return "Critical"
