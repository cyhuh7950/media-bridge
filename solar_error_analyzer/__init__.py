# Solar-4 기반 에러 분석 도구 (폴더 구조 패키지)
#
# 사용법:
#   python3 solar_error_analyzer/cli.py <error_image_path>
#   python3 solar_error_analyzer/cli.py <error_image_path> --context "추가 컨텍스트"
#   python3 solar_error_analyzer/cli.py --text "직접 텍스트 입력"
#   python3 solar_error_analyzer/cli.py --help
#
# 다른 에이전트에서 import 예시:
#   from solar_error_analyzer.core import analyze_error_image, analyze_text_direct, load_api_key
