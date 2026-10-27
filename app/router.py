"""Conservative, inspectable intent/slot baseline; this is not an LLM parser."""
import re
from dataclasses import dataclass

from app.models import AskRequest, Context, Status, Topic


@dataclass
class Decision:
    context: Context
    topic: Topic | None = None
    status: Status | None = None
    reason_code: str = ""
    message: str = ""
    questions: tuple[str, ...] = ()


def contains(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


FARE_PATTERN = r"(?<![a-z_])(?:standard(?:[ _]+plus)?|minimum)(?![a-z_])"


def fare_mentions(text: str) -> set[str]:
    # ASCII boundaries allow Chinese-adjacent names without matching English
    # substrings. Match Standard Plus as one fare, not Standard plus another word.
    return {re.sub(r"[ _]+", "_", match.group()) for match in re.finditer(FARE_PATTERN, text)}


def reported_fare_conflict(text: str) -> bool:
    reports = []
    for speaker in (r"(?:客人|客户|旅客|乘客)(?:说|表示|称|认为)",
                    r"(?:订单|行程单|票面)(?:上)?(?:显示|写着|标注|记录|是)"):
        # Do not cross a clause boundary when associating a fare with its source.
        matches = re.finditer(speaker + r"[^，,。；;！？!?]{0,16}?(" + FARE_PATTERN + r")", text)
        reports.append({re.sub(r"[ _]+", "_", match.group(1)) for match in matches})
    return bool(reports[0] and reports[1] and len(reports[0] | reports[1]) > 1)


def route(request: AskRequest) -> Decision:
    q = request.question.lower()
    ctx = request.context.model_copy(deep=True)

    def stop(status: Status, code: str, message: str, *questions: str):
        return Decision(ctx, status=status, reason_code=code, message=message, questions=questions)

    def clarify(code: str, question: str):
        return stop("needs_clarification", code, "需要补充会影响政策适用的信息。", question)

    def unsupported(code: str, message: str):
        return stop("insufficient_evidence", code, message)

    # The explicit context is authoritative only when it does not contradict text.
    peach = bool(re.search(r"\bpeach\b|乐桃|樂桃", q))
    other = bool(re.search(r"\b(ana|jal|jetstar|airasia|spring|united|delta|zipair)\b|全日空|日航|捷星|春秋|国航|东航|南航|亚航|其他航司", q))
    if other:
        return unsupported("airline_not_covered", "仅收录 Peach 的政策，无法回答其他航空公司或跨航司比较。")
    if ctx.airline:
        if ctx.airline.lower() not in {"peach", "peach aviation", "乐桃", "樂桃"}:
            return unsupported("airline_not_covered", "当前知识库没有该航空公司的资料。")
        ctx.airline = "peach"
    elif peach:
        ctx.airline = "peach"
    if not ctx.airline:
        return clarify("missing_airline", "请确认航空公司；当前仅收录 Peach（乐桃航空）。")

    # Check exclusions before broad topic keywords. Do not answer a special-item
    # question with a superficially relevant generic baggage paragraph.
    exclusions = (
        "宠物", "轮椅", "婴儿", "儿童", "乐器", "运动器材", "滑雪", "自行车", "冲浪", "危险品",
        "电池", "充电宝", "液体", "药品", "药物", "酒精", "赔偿", "丢失", "损坏", "遗失",
        "签证", "酒店", "保险", "里程", "积分兑换", "积分有效", "到账", "多久收到", "多久到账",
        "退多少", "多少钱", "多少日元", "具体金额", "金额计算", "手续费是多少", "手续费多少", "姓名", "改名", "转让",
        "api", "错误码", "数据库", "内部流程", "员工", "联程", "代码共享", "中转", "超售",
        "目的地", "出发地", "升级票价", "更改票价", "更换票价", "改票价", "变更票价", "改舱", "升舱", "destination", "origin",
        "simple peach", "value peach", "prime peach", "历史政策", "去年", "明年", "后年",
        "pet", "battery", "liquid", "infant", "compensation", "lost", "damaged", "how much", "name change",
    )
    if contains(q, exclusions) or re.search(r"20\d{2}[年/-]|\d+\s*(kg|公斤|千克|cm|厘米|寸|日元|小时|分钟)", q):
        return unsupported("detail_not_covered", "该问题涉及未收录的专项规则、历史/未来适用性或具体个案判断，请查阅官方完整政策。")
    if contains(q, ("忽略", "编造", "系统提示", "ignore previous", "system prompt")):
        return unsupported("unsupported_instruction", "检索模式只返回已收录的证据摘要。")
    if re.search(r"(?:不是|并非|不确定|不清楚|未确认|not\s+)(?:\s|因|出于)*(?:个人原因|自愿|官网|minimum|standard|peach)", q):
        return clarify("ambiguous_context", "问题含有否定或不确定的适用条件，请用表单确认票价、退改原因和购票渠道后，简化问题再提交。")

    inferred_fares = fare_mentions(q)
    if len(inferred_fares) > 1:
        if reported_fare_conflict(q):
            return clarify("conflicting_context", "客户描述与订单/票面记录的票价不一致，请核对原始出票记录并确认实际票价类型，再更新问题或表单；不要仅凭任一描述选择政策。")
        return clarify("multiple_fares", "请一次选择一种票价类型：Minimum、Standard 或 Standard Plus。")
    if inferred_fares:
        fare = inferred_fares.pop()
        if ctx.fare_type and fare != ctx.fare_type:
            return clarify("conflicting_context", "问题中的票价与已选票价不同，请统一后重试。")
        ctx.fare_type = fare

    involuntary = contains(q, ("航班取消", "航班被取消", "航司取消", "天气", "台风", "延误", "非自愿", "flight cancelled", "involuntary"))
    voluntary = contains(q, ("个人原因", "自愿", "不想去了", "行程变了", "personal reason", "voluntary")) and not involuntary
    inferred_reason = "involuntary" if involuntary else "voluntary" if voluntary else None
    if inferred_reason:
        if ctx.reason and ctx.reason != inferred_reason:
            return clarify("conflicting_context", "问题中的退改原因与已选原因不同，请统一后重试。")
        ctx.reason = inferred_reason
    agency = contains(q, ("旅行社", "代理", "第三方", "skyticket", "携程", "ota", "agency"))
    direct = contains(q, ("官网", "直接购买", "direct", "website"))
    if agency and direct:
        return clarify("conflicting_context", "请确认原订单是在航司官网还是通过旅行社/OTA 购买。")
    inferred_channel = "agency" if agency else "direct" if direct else None
    if inferred_channel:
        if ctx.booking_channel and ctx.booking_channel != inferred_channel:
            return clarify("conflicting_context", "问题中的购票渠道与已选渠道不同，请统一后重试。")
        ctx.booking_channel = inferred_channel

    carry = contains(q, ("随身", "手提", "登机箱", "登机行李", "carry-on", "carry on", "hand luggage"))
    checked = contains(q, ("托运", "託運", "checked"))
    # Recognize intent without deriving fare family from price or assuming why
    # a customer stopped travelling. Those conditions must still be confirmed.
    change = contains(q, ("改签", "改期", "变更", "更改", "change", "reschedul")) or bool(
        re.search(r"(?:换|改)(?:一|个|另一|到|成)?(?:天|日期|日子)(?:再)?(?:飞|出发)", q))
    cancel = contains(q, ("取消", "退票", "退款", "退钱", "cancel", "refund")) or bool(
        re.search(r"(?:机票|这张票|这票|票款)[^，,。；;！？!?]{0,8}(?:能退|可以退|退吗|能不能退)", q))
    groups = sum([carry or checked, change, cancel])
    if groups > 1 or (carry and checked):
        return clarify("multiple_topics", "请一次询问一个主题：随身行李、托运行李、改签或取消。")
    if carry:
        if not contains(q, ("重量", "尺寸", "件数", "几件", "多重", "多大", "限额", "限制", "规定", "规则", "政策", "要求", "额度", "weight", "size", "allowance", "limit", "policy")):
            return unsupported("detail_not_covered", "随身行李摘要仅覆盖件数、总重量与普通尺寸要求，无法回答该项细节。")
        return Decision(ctx, topic="carry_on")
    if checked:
        limits = contains(q, ("重量", "尺寸", "上限", "限制", "多重", "多大", "weight", "size", "limit"))
        allowance = contains(q, ("免费", "包含", "额度", "free", "included", "allowance"))
        if limits and allowance:
            return clarify("multiple_topics", "请分别查询免费托运额度和托运行李重量/尺寸限制。")
        if contains(q, ("费用", "价格", "收费", "购买", "加购", "fee", "cost", "buy", "purchase")) and not allowance:
            return unsupported("detail_not_covered", "尚未收录托运行李购买流程或收费表，无法据此判断费用与办理方式。")
        if limits:
            return Decision(ctx, topic="checked_limits")
        if allowance:
            if not ctx.fare_type:
                return clarify("missing_fare_type", "请提供票价类型：Minimum、Standard 或 Standard Plus。")
            return Decision(ctx, topic="checked_allowance")
        return clarify("missing_baggage_detail", "你想查询托运行李的免费额度，还是重量/尺寸限制？")
    if change or cancel:
        if ctx.reason == "involuntary":
            return unsupported("disruption_not_covered", "本版未收录航班取消、延误等非自愿退改细则，不能套用个人原因退改政策。")
        if ctx.booking_channel == "agency":
            return unsupported("agency_not_covered", "本版未收录旅行社/OTA 的订单办理规则，无法确认该渠道的退改安排。")
        missing = []
        if not ctx.fare_type:
            missing.append("票价类型（Minimum / Standard / Standard Plus）")
        if not ctx.reason:
            missing.append("退改原因（个人原因 / 航班取消或延误）")
        if not ctx.booking_channel:
            missing.append("购票渠道（航司官网 / 旅行社或 OTA）")
        if missing:
            return clarify("missing_policy_context", "请补充：" + "、".join(missing) + "。")
        if contains(q, ("办理流程", "操作步骤", "怎么操作", "如何操作", "怎么申请", "操作", "部分乘客", "机场", "客服中心", "how to", "procedure", "步骤")):
            return unsupported("detail_not_covered", "本版仅覆盖一般退改资格、返还方式和截止时间，尚未收录具体办理步骤或非官网渠道收费。")
        return Decision(ctx, topic="change" if change else "cancel")
    if "行李" in q or "baggage" in q:
        return clarify("missing_baggage_type", "请说明查询随身行李还是托运行李。")
    return unsupported("topic_not_covered", "未找到受支持的政策主题。当前覆盖一般随身行李、托运额度/限制及个人原因退改政策。")
