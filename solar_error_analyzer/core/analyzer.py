"""
에러 분석 파이프라인 모듈
=======================
OCR 엔진 + LLM 백엔드를 결합하여 에러 이미지를 분석한다.

사용 예:
    from solar_error_analyzer.core.analyzer import SolarErrorAnalyzer, analyze_error_image
    
    # 팩토리로 생성 (설정 기반)
    config = {
        "ocr": {"type": "upstage-parse", "api_key": "up_xxx..."},
        "llm": {"type": "solar", "model": "solar-pro4", "api_key": "up_xxx..."}
    }
    analyzer = SolarErrorAnalyzer(config)
    result = analyzer.analyze(image_path="error.png")
    
    # 또는 기본 팩토리 사용
    from solar_error_analyzer.core.factory import AnalyzerFactory
    analyzer = AnalyzerFactory.create_analyzer({"ocr": {"type": "upstage-parse"}, "llm": {"type": "solar"}})
    result = analyzer.analyze(image_path="error.png")
    
    # 간단한 함수 (디폴트 엔진/백엔드 사용)
    from solar_error_analyzer.core.analyzer import analyze_error_image
    result = analyze_error_image("error.png", context="Flask 앱")
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any

from .ocr_engines import BaseOcrEngine, create_ocr_engine
from .llm_backends import BaseLLMBackend, create_llm_backend


class SolarErrorAnalyzer:
    """
    에러 이미지 분석기.
    
    OCR 엔진으로 이미지에서 텍스트를 추출하고,
    LLM 백엔드로 텍스트를 분석하여 에러 원인과 수정 방법을 제시한다.
    
    사용 예:
        # 팩토리로 생성
        config = {
            "ocr": {"type": "upstage-parse", "api_key": "up_xxx..."},
            "llm": {"type": "solar", "model": "solar-pro4", "api_key": "up_xxx..."}
        }
        analyzer = SolarErrorAnalyzer(config)
        result = analyzer.analyze(image_path="error.png", context="Flask 앱")
        
        # 직접 엔진/백엔드 지정
        from .ocr_engines import UpstageParseOcr
        from .llm_backends import SolarLLM
        ocr = UpstageParseOcr(api_key="up_xxx...")
        llm = SolarLLM(api_key="up_xxx...", model="solar-pro4")
        analyzer = SolarErrorAnalyzer(ocr=ocr, llm=llm)
        result = analyzer.analyze(image_path="error.png", context="Flask 앱")
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 ocr: Optional[BaseOcrEngine] = None,
                 llm: Optional[BaseLLMBackend] = None):
        """
        분석기 초기화.
        
        Args:
            config: 설정 dict ({"ocr": ..., "llm": ...})
                   config가 제공되면 ocr/llm을 팩토리로 생성
            ocr: 직접 생성한 OCR 엔진 인스턴스 (config와 함께 제공 불가)
            llm: 직접 생성한 LLM 백엔드 인스턴스 (config와 함께 제공 불가)
        
        config 예시:
            {
                "ocr": {"type": "upstage-parse", "api_key": "up_xxx..."},
                "llm": {"type": "solar", "model": "solar-pro4", "api_key": "up_xxx..."}
            }
        """
        if config is not None and (ocr is not None or llm is not None):
            raise ValueError("config와 ocr/llm을 함께 제공할 수 없습니다. 하나만 사용하세요.")
        
        if config is not None:
            ocr_config = config.get("ocr", {})
            llm_config = config.get("llm", {})
            self._ocr = create_ocr_engine(ocr_config)
            self._llm = create_llm_backend(llm_config)
        elif ocr is not None and llm is not None:
            self._ocr = ocr
            self._llm = llm
        else:
            raise ValueError("config 또는 (ocr, llm) 쌍을 제공해야 합니다.")
    
    @property
    def ocr(self) -> BaseOcrEngine:
        return self._ocr
    
    @property
    def llm(self) -> BaseLLMBackend:
        return self._llm
    
    def analyze(self, image_path: str, context: str = "",
                system_prompt: Optional[str] = None) -> Optional[str]:
        """
        에러 이미지 분석.
        
        Args:
            image_path: 에러 이미지 파일 경로
            context: 추가 컨텍스트 (파일 정보, 환경 등)
            system_prompt: LLM에 전달할 시스템 프롬프트 (기본값: 에러 분석 프롬프트)
        
        Returns:
            분석 결과 텍스트 또는 None
        """
        ocr_text = self._ocr.extract_text(image_path)
        if not ocr_text:
            print("❌ OCR 실패. 분석 중단.", file=sys.stderr)
            return None
        
        return self._llm.analyze_error(
            error_text=ocr_text,
            context=context,
            system_prompt=system_prompt
        )
    
    def analyze_text(self, error_text: str, context: str = "",
                      system_prompt: Optional[str] = None) -> Optional[str]:
        """이미지가 아닌 텍스트를 직접 분석."""
        return self._llm.analyze_error(
            error_text=error_text,
            context=context,
            system_prompt=system_prompt
        )


def analyze_error_image(image_path: str, context: str = "",
                         api_key: Optional[str] = None,
                         model: str = "solar-pro4",
                         ocr_model: str = "document-parse",
                         system_prompt: Optional[str] = None) -> Optional[str]:
    """
    에러 이미지 분석 (간단한 함수 버전).
    
    기본값으로 Upstage Parse OCR + Solar-4 LLM을 사용한다.
    API 키, 모델, OCR 모델 등을 직접 지정 가능.
    
    사용 예:
        result = analyze_error_image("error.png", context="Flask 앱")
        result = analyze_error_image("error.png", api_key="up_xxx...", model="solar-pro3")
        result = analyze_error_image("error.png", ocr_model="ocr")
    
    Args:
        image_path: 에러 이미지 파일 경로
        context: 추가 컨텍스트
        api_key: Upstage API 키 (OCR + Solar 둘 다 사용)
        model: Solar 모델 이름
        ocr_model: OCR 모델 이름 ("document-parse" 또는 "ocr")
        system_prompt: 시스템 프롬프트
    
    Returns:
        분석 결과 텍스트 또는 None
    """
    ocr_config = {"type": "upstage-parse"}
    if api_key:
        ocr_config["api_key"] = api_key
    ocr_config["default_model"] = ocr_model
    
    llm_config = {"type": "solar"}
    if api_key:
        llm_config["api_key"] = api_key
    llm_config["model"] = model
    if system_prompt:
        llm_config["system_prompt"] = system_prompt
    
    analyzer = SolarErrorAnalyzer(config={
        "ocr": ocr_config,
        "llm": llm_config
    })
    
    return analyzer.analyze(image_path=image_path, context=context, system_prompt=system_prompt)


def analyze_text_direct(error_text: str, context: str = "",
                         api_key: Optional[str] = None,
                         model: str = "solar-pro4",
                         system_prompt: Optional[str] = None) -> Optional[str]:
    """
    이미지를 거치지 않고 텍스트를 직접 분석.
    
    사용 예:
        result = analyze_text_direct("Traceback...", context="Flask 앱")
        result = analyze_text_direct("Traceback...", api_key="up_xxx...", model="solar-pro3")
    
    Args:
        error_text: 분석할 에러 텍스트
        context: 추가 컨텍스트
        api_key: Upstage API 키
        model: Solar 모델 이름
        system_prompt: 시스템 프롬프트
    
    Returns:
        분석 결과 텍스트 또는 None
    """
    llm_config = {"type": "solar"}
    if api_key:
        llm_config["api_key"] = api_key
    llm_config["model"] = model
    if system_prompt:
        llm_config["system_prompt"] = system_prompt
    
    analyzer = SolarErrorAnalyzer(config={"llm": llm_config})
    return analyzer.analyze_text(error_text=error_text, context=context, system_prompt=system_prompt)
