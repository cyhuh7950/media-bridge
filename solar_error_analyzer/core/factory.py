"""
팩토리 모듈
===========
설정(config) 기반으로 OCR 엔진과 LLM 백엔드를 생성하는 팩토리.

사용 예:
    from solar_error_analyzer.core.factory import AnalyzerFactory
    
    config = {
        "ocr": {"type": "upstage-parse", "api_key": "up_xxx..."},
        "llm": {"type": "solar", "model": "solar-pro4", "api_key": "up_xxx..."}
    }
    analyzer = AnalyzerFactory.create_analyzer(config)
    result = analyzer.analyze(image_path="error.png")
    
    # 또는 개별 생성
    from solar_error_analyzer.core.factory import create_ocr_engine, create_llm_backend
    
    ocr_config = {"type": "tesseract", "lang": "kor+eng"}
    ocr = create_ocr_engine(ocr_config)
    
    llm_config = {"type": "claude", "model": "claude-sonnet-4-20250514"}
    llm = create_llm_backend(llm_config)
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any

from .ocr_engines import BaseOcrEngine, create_ocr_engine as _create_ocr_engine
from .llm_backends import BaseLLMBackend, create_llm_backend as _create_llm_backend


def load_api_key_from_sources(sources: Optional[list] = None) -> Optional[str]:
    """여러 소스에서 API 키를 로딩한다."""
    if sources is None:
        sources = [
            "/home/ubuntu/.hermes/.env",
            "/home/ubuntu/.env",
            str(Path.home() / ".hermes" / ".env"),
            str(Path.home() / ".env"),
            "/home/ubuntu/.env.local",
            str(Path.home() / ".env.local"),
        ]
    
    for fpath in sources:
        if os.path.exists(fpath):
            try:
                with open(fpath) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#"):
                            continue
                        if "=" in line:
                            key, _, value = line.partition("=")
                            key = key.strip()
                            value = value.strip()
                            if key and value:
                                return value
            except Exception:
                pass
    return None


class AnalyzerFactory:
    """
    설정(config) 기반으로 OCR 엔진과 LLM 백엔드를 생성하여
    SolarErrorAnalyzer를 반환하는 팩토리.
    
    설정 예시:
        {
            "ocr": {
                "type": "upstage-parse",
                "api_key_env": "UPSTAGE_API_KEY",
                "api_key": "up_xxx...",
                "default_model": "document-parse",
                "default_ocr": "force"
            },
            "llm": {
                "type": "solar",
                "api_key_env": "UPSTAGE_API_KEY",
                "api_key": "up_xxx...",
                "model": "solar-pro4",
                "temperature": 0.7,
                "max_tokens": 2000,
                "system_prompt": "..."
            }
        }
    
    환경변수 지원:
        - config에서 api_key_env를 지정하면 해당 환경변수를 읽음
        - 환경변수명 미지정 시 기본값 사용 (ocr: UPSTAGE_API_KEY, llm: UPSTAGE_API_KEY)
        - config에서 api_key를 직접 지정하면 환경변수보다 우선
    """
    
    @staticmethod
    def _resolve_api_key(config_entry: dict, default_env: str = "UPSTAGE_API_KEY") -> Optional[str]:
        """config 항목에서 API 키를 해결한다."""
        explicit_key = config_entry.get("api_key")
        if explicit_key:
            return explicit_key
        
        env_var = config_entry.get("api_key_env", default_env)
        return os.environ.get(env_var)
    
    @classmethod
    def create_analyzer(cls, config: Dict[str, Any]) -> "SolarErrorAnalyzer":
        """
        설정 dict로 분석기를 생성한다.
        
        Args:
            config: {"ocr": {...}, "llm": {...}}
        
        Returns:
            SolarErrorAnalyzer 인스턴스
        """
        from .analyzer import SolarErrorAnalyzer
        
        ocr_config = config.get("ocr", {})
        llm_config = config.get("llm", {})
        
        ocr_api_key = cls._resolve_api_key(ocr_config, "UPSTAGE_API_KEY")
        if ocr_api_key:
            ocr_config["api_key"] = ocr_api_key
        
        llm_api_key = cls._resolve_api_key(llm_config, "UPSTAGE_API_KEY")
        if llm_api_key:
            llm_config["api_key"] = llm_api_key
        
        from .ocr_engines import create_ocr_engine
        from .llm_backends import create_llm_backend
        
        ocr = create_ocr_engine(ocr_config)
        llm = create_llm_backend(llm_config)
        
        return SolarErrorAnalyzer(ocr=ocr, llm=llm)
    
    @classmethod
    def create_ocr_engine_from_config(cls, config: Dict[str, Any]) -> BaseOcrEngine:
        """OCR 엔진만 설정 기반으로 생성."""
        from .ocr_engines import create_ocr_engine
        
        api_key = cls._resolve_api_key(config, "UPSTAGE_API_KEY")
        if api_key:
            config = dict(config)
            config["api_key"] = api_key
        
        return create_ocr_engine(config)
    
    @classmethod
    def create_llm_backend_from_config(cls, config: Dict[str, Any]) -> BaseLLMBackend:
        """LLM 백엔드만 설정 기반으로 생성."""
        from .llm_backends import create_llm_backend as _create_llm
        
        api_key = cls._resolve_api_key(config, "UPSTAGE_API_KEY")
        if api_key:
            config = dict(config)
            config["api_key"] = api_key
        
        return _create_llm(config)


def create_analyzer(config: Dict[str, Any]) -> "SolarErrorAnalyzer":
    """편의 함수: 설정 기반 분석기 생성."""
    return AnalyzerFactory.create_analyzer(config)


def create_ocr_engine(config: Dict[str, Any]) -> BaseOcrEngine:
    """편의 함수: OCR 엔진 생성."""
    from .ocr_engines import create_ocr_engine as _create
    
    api_key = load_api_key_from_sources()
    if api_key and "api_key" not in config:
        config = dict(config)
        config["api_key"] = api_key
    
    return _create(config)


def create_llm_backend(config: Dict[str, Any]) -> BaseLLMBackend:
    """편의 함수: LLM 백엔드 생성."""
    from .llm_backends import create_llm_backend as _create
    
    api_key = load_api_key_from_sources()
    if api_key and "api_key" not in config:
        config = dict(config)
        config["api_key"] = api_key
    
    return _create(config)
