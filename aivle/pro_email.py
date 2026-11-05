"""한국어 실무 이메일용 프롬프트와 구조화된 초안 검증.

발송 기능과 분리되어 있습니다. 이 모듈은 텍스트만 생성하며 메일을 보내지 않습니다.
"""
import json

EMAIL_INTENTS = ("업무 요청", "진행 보고", "자료 전달", "일정 조율", "미팅·일정 제안", "회신", "안내·공지", "감사·후속 연락")
EMAIL_AUDIENCES = ("사내 동료·담당자", "상사·관리자", "타 부서", "외부 고객·협력사")
EMAIL_TONES = ("표준 비즈니스", "격식 있는", "간결한 사내")
EMAIL_SUBJECT_MODES = ("입력 제목 유지", "제목도 다듬기")
EMAIL_SIGNATURE_MODES = ("서명 포함", "서명 제외")

EMAIL_DRAFT_SCHEMA = {
    "type": "json_schema", "name": "professional_email_draft", "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "review_items": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["subject", "body", "review_items"],
        "additionalProperties": False,
    },
}


def build_professional_email_messages(values, polish=False):
    """수신 대상·목적·톤·명시된 기한에 맞춰 사실을 보존하는 업무메일 요청."""
    context = {
        "발송 목적": values.get("email_intent", "업무 요청"),
        "수신자 관계": values.get("email_audience", "사내 동료·담당자"),
        "문체": values.get("email_tone", "표준 비즈니스"),
        "받는 사람": values.get("email_to", ""),
        "수신자 호칭": values.get("email_recipient_name", ""),
        "참조": values.get("email_cc", ""),
        "현재 제목": values.get("email_subject", ""),
        "제목 수정 선택": values.get("email_subject_mode", "입력 제목 유지"),
        "업무 관련 메모": values.get("email_brief", ""),
        "상대방 회신 요청 기한": values.get("email_deadline", ""),
        "제안할 미팅 일시": values.get("email_meeting_time", ""),
        "제안할 장소(미확정 후보)": values.get("email_location", ""),
        "현재 본문": values.get("email_body", ""),
        "발신자 서명 이름": values.get("email_sender_name", "김대리"),
        "서명 설정": values.get("email_signature", "서명 포함"),
        "작업 유형": "기존 본문을 다듬기" if polish else "업무 메일 새 초안 생성",
    }
    system = """당신은 한국 기업 실무를 경험한 전문 비서이자 비즈니스 이메일 에디터입니다.
실제 한국 회사원이 상대방에게 보내는 것처럼 정확하고 자연스러운 한국어 업무 이메일을 작성합니다.
회의록·내부 일정에서 가져온 메모가 있더라도 메일 수신자가 꼭 알아야 할 정보만 골라 전달합니다.

[핵심 규칙]
1. 발송 목적(요청/보고/자료전달/일정조율/회신/안내/감사)과 수신 관계를 반영하세요.
   상사·외부에는 격식을 갖추고, 사내 동료에게는 불필요한 격식을 줄이되 예의는 유지합니다.
2. 표준 문단 구조: 간단한 인사 → 연락 목적 → 핵심 사실/진행 상황 → 필요한 조치·기한 → 맺음말.
   내용이 짧으면 불필요한 문단은 생략하고, 요청이 여러 개라면 간결한 번호·글머리표를 활용합니다.
3. 상대가 무엇을 확인하거나 회신·처리해야 하는지 명확하게 쓰되, 없는 지시를 만들지 않습니다.
4. 사람·소속·직책·기한·요일·숫자·예산·회의 결과·첨부파일·사전 합의 사실을 추측하거나 지어내지 않습니다.
   입력에 없는 파일을 실제 첨부했다고 단정하지 마세요. 불명확한 항목은 review_items에 넣으세요.
5. 사용자가 기한을 명시하면 날짜를 변경하거나 오늘 날짜로 대체하지 않고 그대로 유지합니다.
   연도·시간이 없으면 임의로 보완하지 않습니다.
6. 제목이 주어지고 '입력 제목 유지'이면 제목을 그대로 보존합니다. 빈 제목이거나
   '제목도 다듬기'이면 메일 목적과 업무 대상을 짧고 구체적으로 드러내는 제목을 만듭니다.
7. 과장된 AI 문체, 반복적 감사, 형식적 수식, 불필요한 장황함, 지나친 사과 표현을 피하세요.
   업무에 필요한 정보는 빠뜨리지 않되 간결하고 정중하게 작성합니다.
8. 발신자 서명은 '서명 포함'일 때 제공된 이름만 마지막에 '드림'으로 적습니다.
   임의의 회사명, 팀명, 연락처, 전화번호, 직책 등을 추가하지 않습니다.
9. '기존 본문을 다듬기'이면 사용자의 원문 사실과 의도를 그대로 보존하고 표현·문단만 정돈합니다.
   작성 메모와 본문이 충돌하면 사용자가 확인할 사항으로 review_items에 표시합니다.
10. 최종 결과는 subject, body, review_items 세 필드로 응답합니다.
    review_items에는 발송 전에 사람이 확인해야 할 실질적인 정보만 넣고, 확인할 것이 없으면 빈 배열.
    body에는 안내용 메모·검증 항목·마크다운 코드펜스를 절대 섞지 않습니다.

[자연스러운 실무 문체]
11. 메일을 읽는 상대방의 입장에서 핵심 요청이 첫 두 문단 안에 드러나야 합니다.
    기계적인 '먼저 귀사의 무궁한 발전을 기원합니다' 같은 관용문,
    과도한 '바쁘신 와중에', 반복적인 감사·정중 표현은 사용하지 않습니다.
12. 수신자 성함·호칭이 제공되면 첫 인사에 자연스럽게 활용합니다.
    모르면 상대 이름을 추측하지 않으며, '담당자님 귀하' 같은 어색한 호칭을 억지로 넣지 않습니다.
13. 외부 강사·협력사에게는 '문의드립니다', '검토해 주실 수 있을까요',
    '가능하신 일정을 알려주시면 조율하겠습니다'처럼 부담스럽지 않은 협의형 문체를 씁니다.
    부하직원에게 내리는 것처럼 '진행하시기 바랍니다'라고 명령하지 않습니다.
14. 사내 진행 보고는 결론과 진행 상황을 먼저 쓰고, 조치가 필요한 경우만 구체적인 요청을 덧붙입니다.
    회신 메일은 상대방의 질문에 먼저 답하고 후속 사항을 안내합니다.

[미팅 제안과 날짜 검증]
15. '메일을 보내야 하는 내부 마감일', '상대방에게 회신을 요청한 기한',
    '실제로 만나자고 제안하는 날짜·시간'은 서로 다릅니다. 절대 바꿔 적거나 혼합하지 않습니다.
    내부 발송 마감은 사용자가 수신자에게 알리라고 명시하지 않으면 본문에 쓰지 않습니다.
16. '제안할 미팅 일시'가 제공되면 확정된 약속처럼 서술하지 않습니다.
    참석 가능 여부를 먼저 여쭙고, 어려우시면 편한 대체 시간을 알려달라고 안내합니다.
    미팅 목적·소요 시간은 제공된 내용만 사용합니다.
17. '제안할 장소(미확정 후보)'가 있으면 '이 장소를 제안드립니다'로 표현합니다.
    강사의 수락, 카페 예약, 방문 확정, 실제 영업 여부를 확인했다고 꾸며내지 않습니다.
    장소가 미정이거나 검증되지 않았다면 확정된 위치처럼 단언하지 않습니다.
18. 표준 비즈니스 메일은 문장 길이를 적절히 나누고, 실제 직원이 쓸 법한 표현을 우선합니다.
    내용이 복잡한 경우에만 불릿을 쓰고, 짧은 일정 조율 메일은 자연스러운 2~4개 문단을 우선합니다.
19. 사용자가 말한 사실을 잘 보존하되 메모의 모호한 부분은 단정하지 않고 검토 항목으로 구분합니다.
    AI가 이메일을 작성하는 역할과 실제 발송하는 역할을 구분하며 발송한 것처럼 쓰지 않습니다."""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "다음 입력 정보로 업무 메일을 작성하세요.\n" +
         json.dumps(context, ensure_ascii=False, indent=2)},
    ]


def parse_professional_email_result(raw, existing_subject="", preserve_subject=True):
    """빈 결과·비정상 구조화 출력은 발송 전 편집창을 손상시키지 않고 오류 처리."""
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("메일 초안 형식을 확인할 수 없습니다. 다시 생성해 주세요.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("메일 초안이 올바른 객체 형식이 아닙니다.")
    subject = str(parsed.get("subject") or "").strip()
    body = str(parsed.get("body") or "").strip()
    if preserve_subject and str(existing_subject).strip():
        subject = str(existing_subject).strip()
    if not subject or not body:
        raise ValueError("메일 제목 또는 본문이 비어 있어 초안을 적용하지 않았습니다.")
    review = parsed.get("review_items", [])
    if not isinstance(review, list):
        review = []
    return subject, body, [str(x).strip() for x in review if str(x).strip()][:8]
