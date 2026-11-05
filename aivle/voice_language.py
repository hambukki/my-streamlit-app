"""AI 채팅 한국어 응답·음성 안전 검사. 코드/URL/약어는 비한국어 문장으로 오인하지 않습니다."""
import re


_URL = re.compile(r"https?://[^\s)<>]+", re.IGNORECASE)
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(https?://[^)]+\)")
_FOREIGN_SCRIPT = re.compile(
    r"[\u3040-\u30ff\u3400-\u9fff\u0400-\u052f\u0370-\u03ff"
    r"\u0590-\u05ff\u0600-\u06ff\u0900-\u097f\u0e00-\u0e7f]"
)
_LATIN_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
_HANGUL = re.compile(r"[가-힣]")
_KOREAN_FALLBACK = (
    "답변을 한국어로 변환하는 데 문제가 발생했습니다. "
    "잠시 후 다시 질문해 주세요."
)


def remove_nonspoken_markup(text):
    """화면용 URL/코드 표기 때문에 TTS가 언어를 전환하지 않도록 음독 원고를 분리."""
    content = str(text or "")
    content = re.sub(r"```[\s\S]*?```", "코드 예시는 화면에서 확인해 주세요.", content)
    content = _MARKDOWN_LINK.sub(lambda m: m.group(1), content)
    content = _URL.sub("링크는 화면에서 확인해 주세요.", content)
    content = re.sub(r"\*\*|__|(?<!\w)#{1,6}\s*", "", content)
    return content.strip()


def needs_korean_rewrite(text):
    """외국어 자연어 문장만 탐지하며 영문 링크·약어·코드 표기는 예외 처리."""
    text = str(text or "")
    text = re.sub(r"```[\s\S]*?```|`[^`]*`", " ", text)
    text = _MARKDOWN_LINK.sub(" ", text)
    text = _URL.sub(" ", text)
    if _FOREIGN_SCRIPT.search(text):
        return True

    # 한국어 문장과 외국어 문장이 섞일 때도 외국어 문장 하나를 잡아냅니다.
    for part in re.split(r"(?<=[.!?])\s+|\n+", text):
        korean = len(_HANGUL.findall(part))
        words = _LATIN_WORD.findall(part)
        if not words:
            continue
        if len(words) >= 6 and korean < max(5, len(words) // 2):
            return True
        if korean:
            continue
        # 별도로 읽어도 되는 짧은 약어·스펠링 목록은 제외합니다.
        cleaned = re.sub(r"[^A-Za-z0-9\s,;/+._-]", " ", part).strip()
        pieces = _LATIN_WORD.findall(cleaned)
        if pieces and all((w.isupper() and len(w) <= 8) or
                          w in {"OpenAI", "ChatGPT", "Python", "GitHub", "Streamlit", "AIVLE", "Colab", "XGBoost", "TensorFlow"}
                          for w in pieces):
            continue
        return True
    return False


def require_korean_reply(text, translator):
    """비한국어 응답을 번역하고 재검사. 변환 실패 시 외국어 응답을 반환하지 않음."""
    source = str(text or "").strip()
    if not needs_korean_rewrite(source):
        return source
    try:
        translated = str(translator(source) or "").strip()
        source_urls = set(_URL.findall(source))
        if (translated and not needs_korean_rewrite(translated)
                and source_urls.issubset(set(_URL.findall(translated)))):
            return translated
    except Exception:
        pass
    return _KOREAN_FALLBACK


def korean_speech_input(text):
    """TTS 직전 마지막 방어선. 외국어 문장은 절대 그대로 음성화하지 않습니다."""
    spoken = remove_nonspoken_markup(text)
    if not spoken:
        raise ValueError("읽을 한국어 문장이 없습니다.")
    if needs_korean_rewrite(spoken):
        raise ValueError("한국어가 아닌 문장이 감지되어 음성 출력을 중단했습니다.")
    return spoken
