"""
Solar-4 기반 에러 분석 도구 - core 패키지

핵심 모듈:
- ocr_engines.py: OCR 엔진 추상화 및 구현 (Upstage Parse, Tesseract 등)
- llm_backends.py: LLM 백엔드 추상화 및 구현 (Solar-4, Claude, ChatGPT, Gemini, OpenRouter 등)
- analyzer.py: OCR + LLM 결합 파이프라인 (에러 이미지 분석)
- factory.py: 설정 기반 엔진/백엔드 생성 팩토리

사용 예:
    from solar_error_analyzer.core import analyze_error_image, analyze_text_direct
    from solar_error_analyzer.core.ocr_engines import create_ocr_engine
    from solar_error_analyzer.core.llm_backends import create_llm_backend
"""

from .ocr_engines import (
    BaseOcrEngine,
    UpstageParseOcr,
    TesseractOcr,
    create_ocr_engine,
)
from .llm_backends import (
    BaseLLMBackend,
    SolarLLM,
    ClaudeLLM,
    ChatGPTLLM,
    GeminiLLM,
    OpenRouterLLM,
    create_llm_backend,
)
from .analyzer import (
    SolarErrorAnalyzer,
    analyze_error_image,
    analyze_text_direct,
)
from .factory import AnalyzerFactory

__all__ = [
    "BaseOcrEngine",
    "UpstageParseOcr",
    "TesseractOcr",
    "create_ocr_engine",
    "BaseLLMBackend",
    "SolarLLM",
    "ClaudeLLM",
    "ChatGPTLLM",
    "GeminiLLM",
    "OpenRouterLLM",
    "create_llm_backend",
    "SolarErrorAnalyzer",
    "analyze_error_image",
    "analyze_text_direct",
    "AnalyzerFactory",
]
