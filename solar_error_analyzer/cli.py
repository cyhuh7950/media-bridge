#!/usr/bin/env python3
"""
Solar-4 기반 에러 분석 도구 CLI
==============================
에러 이미지 → OCR(Upstage Parse 등) → LLM(Solar-4, Claude, GPT 등) 분석 → 결과 출력

지원 기능:
- 에러 이미지 파일 분석 (PNG, JPG, PDF 등 OCR 지원 형식)
- 에러 텍스트 직접 입력 분석
- OCR 엔진 선택 (Upstage Parse, Tesseract 등)
- LLM 백엔드 선택 (Solar-4, Claude, ChatGPT, Gemini, OpenRouter 등)
- JSON 출력, 색상 제어, 시스템 프롬프트 커스터마이징

사용법:
    python3 cli.py <error_image_path>
    python3 cli.py <error_image_path> --context "Flask 앱입니다"
    python3 cli.py --text "Traceback..."
    python3 cli.py --config config.yaml error.png
    python3 cli.py --ocr upstage-parse --llm solar error.png
    python3 cli.py error.png --json
    python3 cli.py error.png --no-color

환경 변수:
    UPSTAGE_API_KEY: Upstage API 키 (OCR + Solar 사용 시)
    ANTHROPIC_API_KEY: Claude 사용 시
    OPENAI_API_KEY: ChatGPT/GPT 사용 시
    GOOGLE_API_KEY: Gemini 사용 시
    OPENROUTER_API_KEY: OpenRouter 사용 시

설정 파일 (config.yaml) 예시:
    ocr:
      type: upstage-parse
      api_key_env: UPSTAGE_API_KEY
      # api_key: 직접 지정 (환경변수보다 우선)
      # default_model: document-parse
      # default_ocr: force
    llm:
      type: solar
      api_key_env: UPSTAGE_API_KEY
      # api_key: 직접 지정
      model: solar-pro4
      temperature: 0.7
      max_tokens: 2000
      # system_prompt: 커스텀 시스템 프롬프트
"""

import argparse
import json
import sys
import os
from pathlib import Path

# 패키지 import (같은 디렉토리 내에서)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from solar_error_analyzer.core.analyzer import SolarErrorAnalyzer, analyze_error_image, analyze_text_direct
from solar_error_analyzer.core.factory import (
    create_analyzer,
    create_ocr_engine,
    create_llm_backend,
    AnalyzerFactory,
)
from solar_error_analyzer.core.ocr_engines import create_ocr_engine as _create_ocr_engine
from solar_error_analyzer.core.llm_backends import create_llm_backend as _create_llm_backend


def load_config_file(config_path: str) -> dict:
    """YAML 설정 파일을 읽는다."""
    import yaml
    
    config_path = Path(config_path).resolve()
    if not config_path.exists():
        print(f"❌ 설정 파일 없음: {config_path}", file=sys.stderr)
        sys.exit(1)
    
    with open(config_path, "r", encoding="utf-8") as f:
        try:
            config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"❌ YAML 파싱 오류: {e}", file=sys.stderr)
            sys.exit(1)
    
    if not isinstance(config, dict):
        print("❌ 설정 파일이 dict가 아님", file=sys.stderr)
        sys.exit(1)
    
    return config


def merge_config_with_args(config: dict, args) -> dict:
    """설정 파일과 CLI 인자를 병합한다. CLI 인자가 우선."""
    merged = {}
    
    # ocr 설정
    ocr = dict(config.get("ocr", {}))
    if args.ocr:
        ocr["type"] = args.ocr
    if args.ocr_api_key:
        ocr["api_key"] = args.ocr_api_key
    if args.ocr_model:
        ocr["default_model"] = args.ocr_model
    merged["ocr"] = ocr
    
    # llm 설정
    llm = dict(config.get("llm", {}))
    if args.llm:
        llm["type"] = args.llm
    if args.llm_api_key:
        llm["api_key"] = args.llm_api_key
    if args.llm_model:
        llm["model"] = args.llm_model
    if args.llm_temperature is not None:
        llm["temperature"] = args.llm_temperature
    if args.llm_max_tokens is not None:
        llm["max_tokens"] = args.llm_max_tokens
    if args.llm_system_prompt:
        llm["system_prompt"] = args.llm_system_prompt
    merged["llm"] = llm
    
    # 시스템 프롬프트 (상위)
    if args.system_prompt:
        merged["system_prompt"] = args.system_prompt
    
    return merged


def colorize(text: str, color: str) -> str:
    """ANSI 색상 적용."""
    colors = {
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
        "bold": "\033[1m",
        "reset": "\033[0m",
    }
    if color in colors:
        return f"{colors[color]}{text}{colors['reset']}"
    return text


def main():
    parser = argparse.ArgumentParser(
        description="Solar-4 기반 에러 분석 도구 (에러 이미지 → OCR → LLM 분석)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python3 cli.py error.png
  python3 cli.py error.png --context "이 파일은 Flask 앱입니다"
  python3 cli.py --text "Traceback (most recent call last):\n  File \"app.py\", line 42, in get_users\n    users = db.session.query(User).all()\nAttributeError: 'NoneType' object has no attribute 'query'"
  python3 cli.py error.png --config config.yaml
  python3 cli.py error.png --ocr upstage-parse --llm solar
  python3 cli.py error.png --ocr tesseract --llm claude --llm-model claude-sonnet-4-20250514
  python3 cli.py error.png --json
  python3 cli.py error.png --no-color
  python3 cli.py --text "에러 텍스트" --llm openrouter --llm-model claude-sonnet-4-20250514 --llm-api-key "or_xxx..."

환경 변수:
  UPSTAGE_API_KEY: Upstage API 키 (OCR + Solar 사용 시)
  ANTHROPIC_API_KEY: Claude 사용 시
  OPENAI_API_KEY: ChatGPT/GPT 사용 시
  GOOGLE_API_KEY: Gemini 사용 시
  OPENROUTER_API_KEY: OpenRouter 사용 시

설정 파일 (config.yaml) 예시:
  ocr:
    type: upstage-parse
    api_key_env: UPSTAGE_API_KEY
    # api_key: 직접 지정 (환경변수보다 우선)
    # default_model: document-parse
    # default_ocr: force
  llm:
    type: solar
    api_key_env: UPSTAGE_API_KEY
    # api_key: 직접 지정
    model: solar-pro4
    temperature: 0.7
    max_tokens: 2000
    # system_prompt: 커스텀 시스템 프롬프트
""",
    )
    
    parser.add_argument("image", nargs="?", help="에러 이미지 파일 경로 (PNG, JPG, PDF 등)")
    parser.add_argument("--text", help="직접 텍스트 입력 (이미지 대신)")
    parser.add_argument("--context", help="추가 컨텍스트 (파일 정보, 환경 등)")
    parser.add_argument("--config", help="YAML 설정 파일 경로")
    parser.add_argument("--ocr", help="OCR 엔진 타입 (upstage-parse, tesseract 등)")
    parser.add_argument("--ocr-api-key", help="OCR 엔진용 API 키 (직접 지정)")
    parser.add_argument("--ocr-model", help="OCR 모델 (기본: document-parse, 옵션: ocr)")
    parser.add_argument("--llm", help="LLM 백엔드 타입 (solar, claude, chatgpt, gemini, openrouter 등)")
    parser.add_argument("--llm-api-key", help="LLM 백엔드용 API 키 (직접 지정)")
    parser.add_argument("--llm-model", help="LLM 모델 이름 (예: solar-pro4, claude-sonnet-4-20250514, gpt-4o 등)")
    parser.add_argument("--llm-temperature", type=float, help="LLM 온도")
    parser.add_argument("--llm-max-tokens", type=int, help="LLM 최대 토큰")
    parser.add_argument("--llm-system-prompt", help="LLM 시스템 프롬프트")
    parser.add_argument("--system-prompt", help="전체 시스템 프롬프트 (LLM의 시스템 프롬프트 덮어쓰기)")
    parser.add_argument("--json", action="store_true", help="결과를 JSON 형식으로 출력")
    parser.add_argument("--no-color", action="store_true", help="색상 출력 비활성화")
    
    args = parser.parse_args()
    
    # 색상 설정
    use_color = not args.no_color
    
    def c(text, color="reset"):
        return colorize(text, color) if use_color else text
    
    # 설정 파일 + 인자 병합
    config = {}
    if args.config:
        config = load_config_file(args.config)
    
    config = merge_config_with_args(config, args)
    
    # 분석기 생성
    try:
        analyzer = AnalyzerFactory.create_analyzer(config)
    except Exception as e:
        print(f"❌ 분석기 생성 오류: {e}", file=sys.stderr)
        sys.exit(1)
    
    # 분석 실행
    result = None
    try:
        if args.text:
            result = analyzer.analyze_text(error_text=args.text, context=args.context)
        elif args.image:
            result = analyzer.analyze(image_path=args.image, context=args.context)
        else:
            parser.print_help()
            sys.exit(1)
    except Exception as e:
        print(f"❌ 분석 중 오류: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # 결과 출력
    if result:
        if args.json:
            output = {
                "status": "success",
                "analysis": result
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print()
            print(c("=" * 60, "cyan"))
            print(c("Solar-4 분석 결과", "cyan"))
            print(c("=" * 60, "cyan"))
            print(result)
            print(c("=" * 60, "cyan"))
        
        sys.exit(0)
    else:
        if args.json:
            output = {"status": "error", "analysis": None}
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(c("\n❌ 분석 실패", "red"))
        sys.exit(1)


if __name__ == "__main__":
    main()
