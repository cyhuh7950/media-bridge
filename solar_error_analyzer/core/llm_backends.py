"""
LLM 백엔드 모듈
===========
에러 텍스트 분석을 위한 LLM 백엔드들의 추상화 및 구현.

지원하는 LLM 백엔드:
- SolarLLM: Upstage Solar API (https://api.upstage.ai/v1/chat/completions)
- ClaudeLLM: Anthropic Claude API (https://api.anthropic.com/v1/messages)
- ChatGPTLLM: OpenAI GPT API (https://api.openai.com/v1/chat/completions)
- GeminiLLM: Google Gemini API (https://generativelanguage.googleapis.com/v1beta/models)
- OpenRouterLLM: OpenRouter 경유 여러 모델 (https://openrouter.ai/api/v1/chat/completions)

다른 LLM 추가 방법:
    BaseLLMBackend을 상속받아 analyze_error() 메서드 구현 후,
    create_llm_backend() 에 추가 등록

사용 예:
    from solar_error_analyzer.core.llm_backends import SolarLLM, create_llm_backend
    
    # 직접 생성
    llm = SolarLLM(api_key="up_xxx...", model="solar-pro4")
    result = llm.analyze_error("Traceback...", context="Flask 앱")
    
    # 팩토리로 생성 (설정 기반)
    config = {"type": "solar", "model": "solar-pro4"}
    llm = create_llm_backend(config)
    result = llm.analyze_error("Traceback...", context="Flask 앱")
"""

import subprocess
import json
import os
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional

# ============================================================
# LLM 백엔드 베이스 클래스
# ============================================================

class BaseLLMBackend(ABC):
    """LLM 백엔드의 추상 베이스 클래스."""
    
    @abstractmethod
    def analyze_error(self, error_text: str, context: str = "",
                      system_prompt: Optional[str] = None) -> Optional[str]:
        """에러 텍스트를 분석하고 수정 방법을 제시한다."""
        raise NotImplementedError
    
    @abstractmethod
    def name(self) -> str:
        """백엔드 이름을 반환한다."""
        raise NotImplementedError
    
    @abstractmethod
    def model_name(self) -> str:
        """현재 사용 중인 모델 이름을 반환한다."""
        raise NotImplementedError
    
    @property
    @abstractmethod
    def api_key(self) -> Optional[str]:
        """API 키를 반환한다 (설정된 경우)."""
        raise NotImplementedError
    
    def set_api_key(self, api_key: str) -> None:
        """API 키를 설정한다."""
        raise NotImplementedError
    
    def supports_system_prompt(self) -> bool:
        """시스템 프롬프트 지원 여부."""
        return True


# ============================================================
# Solar LLM 백엔드 (Upstage)
# ============================================================

class SolarLLM(BaseLLMBackend):
    """Upstage Solar API 기반 LLM 백엔드."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "solar-pro4",
                 base_url: Optional[str] = None, temperature: float = 0.7,
                 max_tokens: int = 2000, system_prompt: Optional[str] = None):
        self._api_key = api_key or os.environ.get("UPSTAGE_API_KEY")
        self._model = model
        self._base_url = base_url or "https://api.upstage.ai/v1/chat/completions"
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt
    
    @property
    def api_key(self) -> Optional[str]:
        return self._api_key
    
    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key
    
    def name(self) -> str:
        return "solar"
    
    def model_name(self) -> str:
        return self._model
    
    def analyze_error(self, error_text: str, context: str = "",
                      system_prompt: Optional[str] = None) -> Optional[str]:
        """Solar API로 에러 분석."""
        api_key = self._api_key
        if not api_key:
            print("❌ Upstage API 키 없음", file=sys.stderr)
            return None
        
        if not error_text or not error_text.strip():
            print("❌ 분석할 텍스트 없음", file=sys.stderr)
            return None
        
        url = self._base_url
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        sp = system_prompt or self._system_prompt
        if sp is None:
            sp = self._default_solar_system_prompt()
        
        user_message = f"""다음 에러 텍스트를 분석하고 수정 방법을 알려주세요.

## 에러 텍스트
{error_text}

## 추가 컨텍스트 (있으면)
{context if context else "(없음)"}

위 에러의 원인, 위치, 수정 방법을 알려주세요."""

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": sp},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "top_p": 0.9,
            "stream": False
        }
        
        cmd = [
            "curl", "-s", "-X", "POST", url,
            "-H", f"Authorization: Bearer {api_key}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            print("❌ Solar API 타임아웃", file=sys.stderr)
            return None
        except Exception as e:
            print(f"❌ curl 실행 오류: {e}", file=sys.stderr)
            return None
        
        if result.returncode != 0:
            print(f"❌ curl 오류 (코드 {result.returncode})", file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return None
        
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError:
            print(f"⚠️ JSON 파싱 실패. 원문: {result.stdout[:300]}", file=sys.stderr)
            return None
        
        if "choices" in response and len(response["choices"]) > 0:
            return response["choices"][0]["message"]["content"]
        elif "error" in response:
            print(f"❌ Solar API 오류: {response['error'].get('message', '알 수 없음')}", file=sys.stderr)
            return None
        else:
            print(f"⚠️ 예상치 못한 응답 구조", file=sys.stderr)
            return None
    
    def _default_solar_system_prompt(self) -> str:
        return """당신은 Python/코드 에러 분석 전문가입니다.
주어진 에러 텍스트를 분석하여 다음을 제공하세요:
1. 에러 원인 (무엇이 문제인지)
2. 에러가 발생한 위치 (파일, 라인 등)
3. 수정 방법 (코드 수정 예시 포함)
4. 추가 조언 (있으면)

응답은 명확하고 구체적으로 작성하세요. 코드 블록은 적절한 언어 태그로 감싸세요."""


# ============================================================
# Claude LLM 백엔드 (Anthropic)
# ============================================================

class ClaudeLLM(BaseLLMBackend):
    """Anthropic Claude API 기반 LLM 백엔드."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-20250514",
                 temperature: float = 0.7, max_tokens: int = 4000,
                 system_prompt: Optional[str] = None):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt
    
    @property
    def api_key(self) -> Optional[str]:
        return self._api_key
    
    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key
    
    def name(self) -> str:
        return "claude"
    
    def model_name(self) -> str:
        return self._model
    
    def analyze_error(self, error_text: str, context: str = "",
                      system_prompt: Optional[str] = None) -> Optional[str]:
        """Claude API로 에러 분석."""
        api_key = self._api_key
        if not api_key:
            print("❌ Anthropic API 키 없음", file=sys.stderr)
            return None
        
        if not error_text or not error_text.strip():
            print("❌ 분석할 텍스트 없음", file=sys.stderr)
            return None
        
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        
        sp = system_prompt or self._system_prompt
        if sp is None:
            sp = self._default_claude_system_prompt()
        
        user_message = f"""다음 에러 텍스트를 분석하고 수정 방법을 알려주세요.

## 에러 텍스트
{error_text}

## 추가 컨텍스트 (있으면)
{context if context else "(없음)"}

위 에러의 원인, 위치, 수정 방법을 알려주세요."""

        payload = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "system": sp,
            "messages": [
                {"role": "user", "content": user_message}
            ]
        }
        
        cmd = [
            "curl", "-s", "-X", "POST", url,
            "-H", f"Authorization: Bearer {api_key}",
            "-H", "Content-Type: application/json",
            "-H", "anthropic-version: 2023-06-01",
            "-d", json.dumps(payload)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            print("❌ Claude API 타임아웃", file=sys.stderr)
            return None
        except Exception as e:
            print(f"❌ curl 실행 오류: {e}", file=sys.stderr)
            return None
        
        if result.returncode != 0:
            print(f"❌ curl 오류 (코드 {result.returncode})", file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return None
        
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError:
            print(f"⚠️ JSON 파싱 실패. 원문: {result.stdout[:300]}", file=sys.stderr)
            return None
        
        if "content" in response:
            content_blocks = response["content"]
            if content_blocks and len(content_blocks) > 0:
                for block in content_blocks:
                    if block.get("type") == "text":
                        return block.get("text", "")
            print("⚠️ Claude 응답에서 텍스트 블록 없음", file=sys.stderr)
            return None
        
        print(f"⚠️ 예상치 못한 응답 구조", file=sys.stderr)
        return None
    
    def _default_claude_system_prompt(self) -> str:
        return """당신은 Python/코드 에러 분석 전문가입니다.
주어진 에러 텍스트를 분석하여 다음을 제공하세요:
1. 에러 원인 (무엇이 문제인지)
2. 에러가 발생한 위치 (파일, 라인 등)
3. 수정 방법 (코드 수정 예시 포함)
4. 추가 조언 (있으면)

응답은 명확하고 구체적으로 작성하세요. 코드 블록은 적절한 언어 태그로 감싸세요."""


# ============================================================
# ChatGPT (OpenAI) LLM 백엔드
# ============================================================

class ChatGPTLLM(BaseLLMBackend):
    """OpenAI GPT API 기반 LLM 백엔드."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o",
                 temperature: float = 0.7, max_tokens: int = 2000,
                 system_prompt: Optional[str] = None):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt
    
    @property
    def api_key(self) -> Optional[str]:
        return self._api_key
    
    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key
    
    def name(self) -> str:
        return "chatgpt"
    
    def model_name(self) -> str:
        return self._model
    
    def analyze_error(self, error_text: str, context: str = "",
                      system_prompt: Optional[str] = None) -> Optional[str]:
        """OpenAI API로 에러 분석."""
        api_key = self._api_key
        if not api_key:
            print("❌ OpenAI API 키 없음", file=sys.stderr)
            return None
        
        if not error_text or not error_text.strip():
            print("❌ 분석할 텍스트 없음", file=sys.stderr)
            return None
        
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        sp = system_prompt or self._system_prompt
        if sp is None:
            sp = self._default_chatgpt_system_prompt()
        
        user_message = f"""다음 에러 텍스트를 분석하고 수정 방법을 알려주세요.

## 에러 텍스트
{error_text}

## 추가 컨텍스트 (있으면)
{context if context else "(없음)"}

위 에러의 원인, 위치, 수정 방법을 알려주세요."""

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": sp},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "stream": False
        }
        
        cmd = [
            "curl", "-s", "-X", "POST", url,
            "-H", f"Authorization: Bearer {api_key}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            print("❌ ChatGPT API 타임아웃", file=sys.stderr)
            return None
        except Exception as e:
            print(f"❌ curl 실행 오류: {e}", file=sys.stderr)
            return None
        
        if result.returncode != 0:
            print(f"❌ curl 오류 (코드 {result.returncode})", file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return None
        
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError:
            print(f"⚠️ JSON 파싱 실패. 원문: {result.stdout[:300]}", file=sys.stderr)
            return None
        
        if "choices" in response and len(response["choices"]) > 0:
            return response["choices"][0]["message"]["content"]
        elif "error" in response:
            print(f"❌ ChatGPT API 오류: {response['error'].get('message', '알 수 없음')}", file=sys.stderr)
            return None
        else:
            print(f"⚠️ 예상치 못한 응답 구조", file=sys.stderr)
            return None
    
    def _default_chatgpt_system_prompt(self) -> str:
        return """당신은 Python/코드 에러 분석 전문가입니다.
주어진 에러 텍스트를 분석하여 다음을 제공하세요:
1. 에러 원인 (무엇이 문제인지)
2. 에러가 발생한 위치 (파일, 라인 등)
3. 수정 방법 (코드 수정 예시 포함)
4. 추가 조언 (있으면)

응답은 명확하고 구체적으로 작성하세요. 코드 블록은 적절한 언어 태그로 감싸세요."""


# ============================================================
# Gemini LLM 백엔드 (Google)
# ============================================================

class GeminiLLM(BaseLLMBackend):
    """Google Gemini API 기반 LLM 백엔드."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash",
                 temperature: float = 0.7, max_tokens: int = 2000,
                 system_prompt: Optional[str] = None):
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt
    
    @property
    def api_key(self) -> Optional[str]:
        return self._api_key
    
    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key
    
    def name(self) -> str:
        return "gemini"
    
    def model_name(self) -> str:
        return self._model
    
    def analyze_error(self, error_text: str, context: str = "",
                      system_prompt: Optional[str] = None) -> Optional[str]:
        """Gemini API로 에러 분석."""
        api_key = self._api_key
        if not api_key:
            print("❌ Google API 키 없음", file=sys.stderr)
            return None
        
        if not error_text or not error_text.strip():
            print("❌ 분석할 텍스트 없음", file=sys.stderr)
            return None
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        headers = {"Content-Type": "application/json"}
        
        sp = system_prompt or self._system_prompt
        if sp is None:
            sp = self._default_gemini_system_prompt()
        
        user_message = f"""다음 에러 텍스트를 분석하고 수정 방법을 알려주세요.

## 에러 텍스트
{error_text}

## 추가 컨텍스트 (있으면)
{context if context else "(없음)"}

위 에러의 원인, 위치, 수정 방법을 알려주세요."""

        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": user_message}]}
            ],
            "generationConfig": {
                "temperature": self._temperature,
                "maxOutputTokens": self._max_tokens,
            }
        }
        
        if sp:
            payload["contents"] = [
                {"role": "user", "parts": [{"text": sp}]},
                {"role": "user", "parts": [{"text": user_message}]}
            ]
        
        cmd = [
            "curl", "-s", "-X", "POST", url,
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload)
        ]
        cmd[3] = f"{url}?key={api_key}"
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            print("❌ Gemini API 타임아웃", file=sys.stderr)
            return None
        except Exception as e:
            print(f"❌ curl 실행 오류: {e}", file=sys.stderr)
            return None
        
        if result.returncode != 0:
            print(f"❌ curl 오류 (코드 {result.returncode})", file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return None
        
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError:
            print(f"⚠️ JSON 파싱 실패. 원문: {result.stdout[:300]}", file=sys.stderr)
            return None
        
        if "candidates" in response and len(response["candidates"]) > 0:
            candidate = response["candidates"][0]
            if "content" in candidate and "parts" in candidate["content"]:
                parts = candidate["content"]["parts"]
                for part in parts:
                    if "text" in part:
                        return part["text"]
            print("⚠️ Gemini 응답에서 텍스트 파트 없음", file=sys.stderr)
            return None
        
        if "error" in response:
            error_data = response["error"]
            print(f"❌ Gemini API 오류: {error_data.get('message', '알 수 없음')}", file=sys.stderr)
            return None
        
        print(f"⚠️ 예상치 못한 응답 구조", file=sys.stderr)
        return None
    
    def _default_gemini_system_prompt(self) -> str:
        return """당신은 Python/코드 에러 분석 전문가입니다.
주어진 에러 텍스트를 분석하여 다음을 제공하세요:
1. 에러 원인 (무엇이 문제인지)
2. 에러가 발생한 위치 (파일, 라인 등)
3. 수정 방법 (코드 수정 예시 포함)
4. 추가 조언 (있으면)

응답은 명확하고 구체적으로 작성하세요. 코드 블록은 적절한 언어 태그로 감싸세요."""


# ============================================================
# OpenRouter LLM 백엔드
# ============================================================

class OpenRouterLLM(BaseLLMBackend):
    """OpenRouter 경유 LLM 백엔드."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "solar-pro4",
                 temperature: float = 0.7, max_tokens: int = 2000,
                 system_prompt: Optional[str] = None, provider: Optional[str] = None):
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt
        self._provider = provider
    
    @property
    def api_key(self) -> Optional[str]:
        return self._api_key
    
    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key
    
    def name(self) -> str:
        return "openrouter"
    
    def model_name(self) -> str:
        return self._model
    
    def analyze_error(self, error_text: str, context: str = "",
                      system_prompt: Optional[str] = None) -> Optional[str]:
        """OpenRouter API로 에러 분석."""
        api_key = self._api_key
        if not api_key:
            print("❌ OpenRouter API 키 없음", file=sys.stderr)
            return None
        
        if not error_text or not error_text.strip():
            print("❌ 분석할 텍스트 없음", file=sys.stderr)
            return None
        
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com"
        }
        
        sp = system_prompt or self._system_prompt
        if sp is None:
            sp = self._default_openrouter_system_prompt()
        
        user_message = f"""다음 에러 텍스트를 분석하고 수정 방법을 알려주세요.

## 에러 텍스트
{error_text}

## 추가 컨텍스트 (있으면)
{context if context else "(없음)"}

위 에러의 원인, 위치, 수정 방법을 알려주세요."""

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": sp},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "stream": False
        }
        
        if self._provider:
            payload["models"] = [self._model]
        
        cmd = [
            "curl", "-s", "-X", "POST", url,
            "-H", f"Authorization: Bearer {api_key}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            print("❌ OpenRouter API 타임아웃", file=sys.stderr)
            return None
        except Exception as e:
            print(f"❌ curl 실행 오류: {e}", file=sys.stderr)
            return None
        
        if result.returncode != 0:
            print(f"❌ curl 오류 (코드 {result.returncode})", file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return None
        
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError:
            print(f"⚠️ JSON 파싱 실패. 원문: {result.stdout[:300]}", file=sys.stderr)
            return None
        
        if "choices" in response and len(response["choices"]) > 0:
            return response["choices"][0]["message"]["content"]
        elif "error" in response:
            print(f"❌ OpenRouter API 오류: {response['error'].get('message', '알 수 없음')}", file=sys.stderr)
            return None
        else:
            print(f"⚠️ 예상치 못한 응답 구조", file=sys.stderr)
            return None
    
    def _default_openrouter_system_prompt(self) -> str:
        return """당신은 Python/코드 에러 분석 전문가입니다.
주어진 에러 텍스트를 분석하여 다음을 제공하세요:
1. 에러 원인 (무엇이 문제인지)
2. 에러가 발생한 위치 (파일, 라인 등)
3. 수정 방법 (코드 수정 예시 포함)
4. 추가 조언 (있으면)

응답은 명확하고 구체적으로 작성하세요. 코드 블록은 적절한 언어 태그로 감싸세요."""


# ============================================================
# 팩토리 함수
# ============================================================

def create_llm_backend(config: dict) -> BaseLLMBackend:
    """설정 dict 기반으로 LLM 백엔드를 생성한다.
    
    Args:
        config: {"type": "solar"|"claude"|"chatgpt"|"gemini"|"openrouter", ...}
    
    설정 예시:
        {"type": "solar"}
        {"type": "solar", "model": "solar-pro4"}
        {"type": "claude"}
        {"type": "chatgpt", "model": "gpt-4o"}
        {"type": "gemini", "model": "gemini-2.0-flash"}
        {"type": "openrouter", "model": "solar-pro4"}
    """
    backend_type = config.get("type", "solar")
    
    if backend_type == "solar":
        return SolarLLM(
            api_key=config.get("api_key"),
            model=config.get("model", "solar-pro4"),
            base_url=config.get("base_url"),
            temperature=config.get("temperature", 0.7),
            max_tokens=config.get("max_tokens", 2000),
            system_prompt=config.get("system_prompt")
        )
    elif backend_type == "claude":
        return ClaudeLLM(
            api_key=config.get("api_key"),
            model=config.get("model", "claude-sonnet-4-20250514"),
            temperature=config.get("temperature", 0.7),
            max_tokens=config.get("max_tokens", 4000),
            system_prompt=config.get("system_prompt")
        )
    elif backend_type == "chatgpt":
        return ChatGPTLLM(
            api_key=config.get("api_key"),
            model=config.get("model", "gpt-4o"),
            temperature=config.get("temperature", 0.7),
            max_tokens=config.get("max_tokens", 2000),
            system_prompt=config.get("system_prompt")
        )
    elif backend_type == "gemini":
        return GeminiLLM(
            api_key=config.get("api_key"),
            model=config.get("model", "gemini-2.0-flash"),
            temperature=config.get("temperature", 0.7),
            max_tokens=config.get("max_tokens", 2000),
            system_prompt=config.get("system_prompt")
        )
    elif backend_type == "openrouter":
        return OpenRouterLLM(
            api_key=config.get("api_key"),
            model=config.get("model", "solar-pro4"),
            temperature=config.get("temperature", 0.7),
            max_tokens=config.get("max_tokens", 2000),
            system_prompt=config.get("system_prompt"),
            provider=config.get("provider")
        )
    else:
        raise ValueError(f"지원되지 않는 LLM 백엔드 타입: {backend_type}")
