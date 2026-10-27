"""
NLP-based Prompt Defense using a trained DistilBERT classifier exported to ONNX.
Provides real-time malicious prompt detection with confidence scoring.
"""

from pathlib import Path
from typing import Dict, List, Union

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer


class MLPromptSafetyDetector:
    """
    Machine Learning-based prompt safety detector using DistilBERT.
    Detects malicious prompts with confidence scoring and risk level classification.
    """

    REQUIRED_FILES = ("model.onnx", "tokenizer.json")

    def __init__(
        self,
        model_path= "/app/AI/API/models/malicious_prompt_detector",
        confidence_threshold: float = 0.5,
    ):
        """
        Initialize the ML-based prompt safety detector.
        
        Args:
            model_path: Path to saved model directory
            confidence_threshold: Threshold for malicious classification (0-1)
        """
        self.model_path = Path(model_path)
        print(f"Initializing MLPromptSafetyDetector with model path: {self.model_path}")
        self.confidence_threshold = confidence_threshold
        self.session = None
        self.tokenizer = None
        self.max_length = 256
        self.is_loaded = False
        self.load_error: str | None = None
        
        self.load_model()

    def _missing_model_message(self) -> str:
        return (
            f"NLP defense model not found at {self.model_path}. "
            "Download the model zip and unzip it into models/malicious_prompt_detector, "
            "so that model.onnx and tokenizer.json sit directly in it (see the README)."
        )

    def _has_required_files(self) -> bool:
        return self.model_path.is_dir() and all(
            (self.model_path / name).is_file() for name in self.REQUIRED_FILES
        )

    def load_model(self):
        """Load tokenizer and model from disk."""
        if not self._has_required_files():
            self.load_error = self._missing_model_message()
            print(f"⚠️ WARNING: {self.load_error}")
            self.is_loaded = False
            return
        
        try:
            self.tokenizer = Tokenizer.from_file(str(self.model_path / "tokenizer.json"))
            self.tokenizer.enable_truncation(max_length=self.max_length)
            self.session = ort.InferenceSession(
                str(self.model_path / "model.onnx"), providers=["CPUExecutionProvider"]
            )
            self.is_loaded = True
            self.load_error = None
            print(f"✓ Model loaded from {self.model_path}")
        except Exception as e:
            self.load_error = f"Failed to load NLP defense model from {self.model_path}: {e}"
            print(f"✗ Error loading model: {e}")
            self.is_loaded = False

    def detect(
        self,
        prompt: Union[str, List[str]],
        return_details: bool = True,
    ) -> Union[Dict, List[Dict]]:
        """
        Detect if prompt(s) are malicious.
        
        Args:
            prompt: Single prompt string or list of prompts
            return_details: Whether to return probability and confidence
            
        Returns:
            Single dict or list of dicts with predictions
        """
        if not self.is_loaded:
            return self._default_response(prompt, "Model not loaded")
        
        # Handle single prompt
        if isinstance(prompt, str):
            return self._detect_single(prompt, return_details)
        
        # Handle multiple prompts
        return [self._detect_single(p, return_details) for p in prompt]

    def _detect_single(self, prompt: str, return_details: bool) -> Dict:
        """Detect single prompt."""
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

        is_malicious = malicious_prob >= self.confidence_threshold

        result = {
            "is_malicious": is_malicious,
            "classification": "Malicious" if is_malicious else "Benign",
        }
        
        if return_details:
            result.update({
                "confidence": max(benign_prob, malicious_prob),
                "benign_probability": benign_prob,
                "malicious_probability": malicious_prob,
                "confidence_threshold": self.confidence_threshold,
                "risk_level": self.get_risk_level(malicious_prob),
            })
        
        return result

    def set_threshold(self, threshold: float):
        """
        Adjust confidence threshold for malicious classification.
        
        Args:
            threshold: Value between 0 and 1
        """
        if not 0 <= threshold <= 1:
            raise ValueError("Threshold must be between 0 and 1")
        self.confidence_threshold = threshold

    def get_risk_level(self, malicious_probability: float) -> str:
        """
        Classify risk level based on malicious probability.
        
        Args:
            malicious_probability: Probability from model
            
        Returns:
            Risk level: 'Low', 'Medium', 'High', 'Critical'
        """
        if malicious_probability < 0.25:
            return "Low"
        elif malicious_probability < 0.50:
            return "Medium"
        elif malicious_probability < 0.75:
            return "High"
        else:
            return "Critical"

    def _default_response(self, prompt, error_msg="Error") -> Dict:
        """Return default response when model is not available."""
        return {
            "is_malicious": False,
            "classification": "Benign",
            "confidence": 0.0,
            "benign_probability": 0.0,
            "malicious_probability": 0.0,
            "confidence_threshold": self.confidence_threshold,
            "risk_level": "Low",
            "error": error_msg,
        }


# Utility function for API integration
def create_ml_safety_detector(
    model_path: str = "/app/AI/API/models/malicious_prompt_detector",
    confidence_threshold: float = 0.5,
) -> MLPromptSafetyDetector:
    """
    Factory function to create ML-based safety detector instance.
    Can be used in FastAPI routes.
    
    Args:
        model_path: Path to trained model
        confidence_threshold: Detection threshold
        
    Returns:
        MLPromptSafetyDetector instance
    """
    return MLPromptSafetyDetector(model_path, confidence_threshold)
