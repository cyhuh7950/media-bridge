"""
OCR 엔진 모듈
===========
에러 이미지에서 텍스트를 추출하기 위한 OCR/파싱 엔진들의 추상화 및 구현.

지원하는 OCR 엔진:
- UpstageParseOcr: Upstage Parse API 사용 (https://api.upstage.ai/v1/document-digitization)
- TesseractOcr: 로컬 Tesseract CLI 사용 (설치 필요)

다른 엔진 추가 방법:
    BaseOcrEngine을 상속받아 extract_text() 메서드 구현 후,
    create_ocr_engine() 에 추가 등록

사용 예:
    from solar_error_analyzer.core.ocr_engines import UpstageParseOcr, create_ocr_engine
    
    # 직접 생성
    ocr = UpstageParseOcr(api_key="up_xxx...")
    text = ocr.extract_text("error.png")
    
    # 팩토리로 생성 (설정 기반)
    config = {"type": "upstage-parse"}
    ocr = create_ocr_engine(config)
    text = ocr.extract_text("error.png")
"""

import subprocess
import json
import os
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional

# ============================================================
# OCR 엔진 베이스 클래스
# ============================================================

class BaseOcrEngine(ABC):
    """OCR 엔진의 추상 베이스 클래스."""
    
    @abstractmethod
    def extract_text(self, image_path: str, **kwargs) -> Optional[str]:
        """이미지 파일에서 텍스트를 추출한다."""
        raise NotImplementedError
    
    @abstractmethod
    def name(self) -> str:
        """엔진 이름을 반환한다."""
        raise NotImplementedError
    
    @abstractmethod
    def supports_format(self, ext: str) -> bool:
        """주어진 파일 확장자를 지원하는지 확인한다."""
        raise NotImplementedError


# ============================================================
# Upstage Parse OCR 엔진
# ============================================================

class UpstageParseOcr(BaseOcrEngine):
    """
    Upstage Parse API 기반 OCR 엔진.
    
    API 엔드포인트: https://api.upstage.ai/v1/document-digitization
    인증: Bearer 토큰 (UPSTAGE_API_KEY)
    요청 형식: multipart/form-data (파일 업로드 + 파라미터)
    
    지원 형식: JPEG, PNG, BMP, PDF, TIFF, HEIC, DOCX, PPTX, XLSX, HWP, HWPX
    최대 파일 크기: 50MB
    최대 페이지: Sync 100페이지
    """
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 default_model: str = "document-parse", default_ocr: str = "force"):
        """초기화.
        
        Args:
            api_key: Upstage API 키 (미설정 시 UPSTAGE_API_KEY 환경변수 사용)
            base_url: API 엔드포인트 (기본: https://api.upstage.ai/v1/document-digitization)
            default_model: 기본 파싱 모델 ("document-parse" 또는 "ocr")
            default_ocr: 기본 OCR 모드 ("force" 또는 "auto")
        """
        self._api_key = api_key or os.environ.get("UPSTAGE_API_KEY")
        self._base_url = base_url or "https://api.upstage.ai/v1/document-digitization"
        self._default_model = default_model
        self._default_ocr = default_ocr
    
    def name(self) -> str:
        return "upstage-parse"
    
    def supports_format(self, ext: str) -> bool:
        supported = {'.png', '.jpg', '.jpeg', '.bmp', '.pdf', '.tiff',
                     '.heic', '.heif', '.docx', '.pptx', '.xlsx', '.hwp', '.hwpx'}
        return ext.lower() in supported
    
    def extract_text(self, image_path: str, api_key: Optional[str] = None,
                     model: Optional[str] = None, ocr: Optional[str] = None,
                     **kwargs) -> Optional[str]:
        """Upstage Parse API로 이미지 → 텍스트 추출."""
        api_key = api_key or self._api_key
        if not api_key:
            print("❌ Upstage API 키 없음", file=sys.stderr)
            return None
        
        image_file = Path(image_path)
        if not image_file.exists():
            print(f"❌ 이미지 파일 없음: {image_path}", file=sys.stderr)
            return None
        
        model = model or self._default_model
        ocr = ocr or self._default_ocr
        
        cmd = [
            "curl", "-s", "-X", "POST", self._base_url,
            "-H", f"Authorization: Bearer {api_key}",
            "-F", f"document=@{image_file.resolve()}",
            "-F", f"ocr={ocr}",
            "-F", f"model={model}"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            print("❌ Parse API 타임아웃", file=sys.stderr)
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
        
        if "pages" in response:
            texts = [page.get("text", "") for page in response.get("pages", [])]
            ocr_text = "\n".join(texts)
            if not ocr_text.strip():
                print("⚠️ OCR 결과 텍스트 없음", file=sys.stderr)
                return None
            return ocr_text
        
        if "error" in response:
            print(f"❌ Parse API 오류: {response['error'].get('message', '알 수 없음')}", file=sys.stderr)
            return None
        
        print(f"⚠️ 예상치 못한 응답 구조", file=sys.stderr)
        return None


# ============================================================
# Tesseract OCR 엔진 (로컬)
# ============================================================

class TesseractOcr(BaseOcrEngine):
    """
    로컬 Tesseract CLI 기반 OCR 엔진.
    
    설치 필요:
        sudo apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-kor
    
    기본 언어: eng (영어)
    추가 언어: kor (한국어) 등 -l kor -l eng 형태로 지정 가능
    """
    
    def __init__(self, tesseract_cmd: str = "tesseract",
                 default_lang: str = "eng", default_psm: int = 6):
        """초기화.
        
        Args:
            tesseract_cmd: tesseract 실행 파일 경로 (기본: "tesseract")
            default_lang: 기본 언어 코드 (기본: "eng")
            default_psm: 기본 페이지 세그멘테이션 모드 (기본: 6)
        """
        self._tesseract_cmd = tesseract_cmd
        self._default_lang = default_lang
        self._default_psm = default_psm
    
    def name(self) -> str:
        return "tesseract"
    
    def supports_format(self, ext: str) -> bool:
        supported = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.gif'}
        return ext.lower() in supported
    
    def extract_text(self, image_path: str, lang: Optional[str] = None,
                     psm: Optional[int] = None, **kwargs) -> Optional[str]:
        """Tesseract CLI로 이미지 → 텍스트 추출."""
        lang = lang or self._default_lang
        psm = psm or self._default_psm
        
        image_file = Path(image_path)
        if not image_file.exists():
            print(f"❌ 이미지 파일 없음: {image_path}", file=sys.stderr)
            return None
        
        output_base = image_file.stem
        output_file = image_file.parent / f"{output_base}_ocr.txt"
        
        cmd = [
            self._tesseract_cmd,
            str(image_file.resolve()),
            str(output_base),
            "-l", lang,
            "--psm", str(psm)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            print("❌ Tesseract 타임아웃", file=sys.stderr)
            return None
        except FileNotFoundError:
            print("❌ Tesseract 실행 파일 없음. 설치 필요: sudo apt install tesseract-ocr", file=sys.stderr)
            return None
        except Exception as e:
            print(f"❌ Tesseract 실행 오류: {e}", file=sys.stderr)
            return None
        
        if result.returncode != 0:
            print(f"❌ Tesseract 오류 (코드 {result.returncode})", file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return None
        
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                ocr_text = f.read()
            output_file.unlink(missing_ok=True)
            if not ocr_text.strip():
                print("⚠️ Tesseract 결과 텍스트 없음", file=sys.stderr)
                return None
            return ocr_text
        except Exception as e:
            print(f"❌ Tesseract 결과 읽기 오류: {e}", file=sys.stderr)
            try:
                output_file.unlink(missing_ok=True)
            except Exception:
                pass
            return None


# ============================================================
# 팩토리 함수
# ============================================================

def create_ocr_engine(config: dict) -> BaseOcrEngine:
    """설정 dict 기반으로 OCR 엔진을 생성한다.
    
    Args:
        config: {"type": "upstage-parse"|"tesseract", ...추가 인자}
    
    설정 예시:
        {"type": "upstage-parse"}
        {"type": "upstage-parse", "api_key": "up_xxx..."}
        {"type": "tesseract"}
        {"type": "tesseract", "lang": "kor+eng", "psm": 6}
    """
    engine_type = config.get("type", "upstage-parse")
    
    if engine_type == "upstage-parse":
        return UpstageParseOcr(
            api_key=config.get("api_key"),
            base_url=config.get("base_url"),
            default_model=config.get("default_model", "document-parse"),
            default_ocr=config.get("default_ocr", "force")
        )
    elif engine_type == "tesseract":
        return TesseractOcr(
            tesseract_cmd=config.get("tesseract_cmd", "tesseract"),
            default_lang=config.get("lang", "eng"),
            default_psm=config.get("psm", 6)
        )
    else:
        raise ValueError(f"지원되지 않는 OCR 엔진 타입: {engine_type}")
