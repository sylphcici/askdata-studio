from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .errors import PipelineStageError
from .model_client import ModelClient


RouteName = Literal["data_qa", "database_query", "direct_response"]
ResponseType = Literal["answer", "clarification"]
logger = logging.getLogger(__name__)


@dataclass
class RetrievalIntent:
    """Schema 检索参数。"""

    retrieval_terms: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    time_expressions: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreparedRequest:
    """请求预处理结果。"""

    action: RouteName
    confidence: float
    reason: str
    standalone_query: str = ""
    rewritten: bool = False
    retrieval: RetrievalIntent = field(default_factory=RetrievalIntent)
    response: str = ""
    response_type: ResponseType = "answer"
    source: str = "model"
    clarification: dict[str, Any] | None = None


class RequestPreprocessor:
    """一次调用完成上下文聚合、意图判断、检索词提取或直接回复。"""

    def __init__(self, model_client: ModelClient) -> None:
        self.model_client = model_client

    def prepare(self, query: str, recent_context: str) -> PreparedRequest:
        business_clarification = self._ambiguous_regional_average_price(
            query, recent_context
        )
        if business_clarification:
            return business_clarification
        system = """你是问数系统的请求预处理器，一次完成上下文聚合、意图判断和必要回复。

意图边界：
1. database_query：用户明确要求查询新的数据库数据，例如获取指标、明细、排名、统计或对比。
2. data_qa：用户明确要求解释或分析上下文中已经存在的查询结果、表格或数据，不需要查询新数据。
3. direct_response：除以上两类之外的请求，包括闲聊、一般交流、能力询问，以及无法确定是
   查询新数据还是分析已有结果的灰色地带。此类请求由你直接回答；如果缺少的信息会影响
   意图判断，则直接提出一个简短的自然语言问题。不要假装已经查询数据。
指标澄清规则：当用户明确要查询新数据，并给出了对象、维度或筛选范围，但只使用“情况、
表现、怎么样、数据”等宽泛表达，没有明确指定可计算指标时，不得自行补出一个或多个指标。
此时action=database_query，standalone_query保留用户已经表达的信息，并返回clarification：
parameter必须为metric，问题只询问要使用哪个指标。不要重复询问已经明确的维度或筛选条件。

上下文聚合：只在当前问题依赖上文时理解和补全语义，不要拼接无关历史。
处理追问时优先参考最近一轮的standalone_query和interpretation，并遵循以下规则：
1. 继承：本轮未提及的指标、维度、时间和筛选条件沿用上轮，例如“只看华东和华南”。
2. 覆盖：本轮明确给出的新条件替换对应旧条件，例如“换成6月”必须替换上轮月份。
3. 清除：本轮明确要求取消条件时不得继续继承，例如“不限制地区”。
4. 澄清：如果无法确定代词、要修改的对象或用户是否要查询新数据，使用direct_response和
   response_type=clarification提出一个简短问题，不得自行猜测。
standalone_query必须是完整、无须阅读历史也能理解的自然语言查询，不能只写“同上”“只看华东”。
仅当action=database_query时，将问题改写为可独立理解的standalone_query，并提取字段级
Schema检索信息。data_qa和direct_response不提取Schema信息。

只返回JSON：
{
  "action":"database_query|data_qa|direct_response",
  "confidence":0.0,
  "reason":"...",
  "standalone_query":"问数时填写，其他情况为空字符串",
  "rewritten":false,
  "response":"仅direct_response填写自然语言回答或澄清问题",
  "response_type":"answer|clarification",
  "clarification":null或{
    "parameter":"metric",
    "question":"你希望用哪个指标查看这项业务表现？",
    "reason":"不同指标会产生不同的查询结果"
  },
  "retrieval":{
    "retrieval_terms":["用于BM25和Embedding的简短Schema检索词，不要写完整句子"],
    "metrics":[], "dimensions":[], "filters":[],
    "time_expressions":[], "operations":[]
  }
}
database_query必须填写standalone_query和retrieval，response为空。
只有明确缺少指标时database_query才填写clarification，其余情况为null。
data_qa必须清空standalone_query、response和retrieval。
direct_response必须填写response，并清空standalone_query和retrieval。不要猜表名。"""
        user = f"当前问题：{query}\n近期轻量上下文：{recent_context or '无'}"
        try:
            payload = self.model_client.chat_json(system, user)
        except RuntimeError as exc:
            # 预处理失败时终止下游查询，避免错误路由访问数据库。
            logger.warning(
                "route_fallback_used stage=request_preprocessing action=direct_response error=%s",
                exc,
            )
            return PreparedRequest(
                action="direct_response",
                confidence=0.0,
                reason=f"预处理模型不可用，已启用保守兜底：{exc}",
                response="大模型服务暂时不可用，请稍后重试。",
                source="model_unavailable_fallback",
            )
        try:
            return self._parse(payload, query)
        except (ValueError, KeyError, TypeError) as exc:
            raise PipelineStageError("request_preprocessing", str(exc)) from exc

    def _parse(self, payload: dict[str, Any], original_query: str) -> PreparedRequest:
        action = str(payload["action"])
        if action not in {"data_qa", "database_query", "direct_response"}:
            raise ValueError(f"不支持的路由结果：{action}")

        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.8))))
        reason = str(payload.get("reason") or "模型完成请求预处理")

        clarification = payload.get("clarification")
        if action == "database_query" and isinstance(clarification, dict):
            parameter = str(clarification.get("parameter") or "")
            if parameter == "metric":
                raw = payload.get("retrieval") if isinstance(payload.get("retrieval"), dict) else {}
                return PreparedRequest(
                    action="database_query",
                    confidence=confidence,
                    reason=reason,
                    standalone_query=str(payload.get("standalone_query") or original_query).strip()[:800],
                    rewritten=False,
                    retrieval=RetrievalIntent(
                        retrieval_terms=self._strings(raw.get("retrieval_terms")),
                        metrics=[],
                        dimensions=self._strings(raw.get("dimensions")),
                        filters=self._strings(raw.get("filters")),
                        time_expressions=self._strings(raw.get("time_expressions")),
                        operations=self._strings(raw.get("operations")),
                    ),
                    clarification={
                        "parameter": "metric",
                        "question": str(clarification.get("question") or "你希望用哪个指标查看？"),
                        "reason": str(clarification.get("reason") or "不同指标会产生不同的查询结果"),
                        "options": [
                            {"id": "paid_amount", "label": "实付销售额", "description": "按订单实付金额汇总", "recommended": True},
                            {"id": "order_count", "label": "订单量", "description": "按订单数量统计", "recommended": False},
                            {"id": "average_order_value", "label": "客单价", "description": "按实付金额除以订单量计算", "recommended": False},
                        ],
                    },
                )

        if action == "data_qa":
            return PreparedRequest(action="data_qa", confidence=confidence, reason=reason)

        if action == "direct_response":
            response = str(payload.get("response") or "").strip()
            if not response:
                raise ValueError("direct_response缺少response")
            response_type = str(payload.get("response_type") or "answer")
            if response_type not in {"answer", "clarification"}:
                raise ValueError(f"不支持的直接回复类型：{response_type}")
            return PreparedRequest(
                action="direct_response",
                confidence=confidence,
                reason=reason,
                response=response,
                response_type=response_type,
            )

        standalone = str(payload.get("standalone_query") or original_query).strip()[:800]
        raw = payload.get("retrieval") if isinstance(payload.get("retrieval"), dict) else {}
        retrieval = RetrievalIntent(
            retrieval_terms=self._strings(raw.get("retrieval_terms")),
            metrics=self._strings(raw.get("metrics")),
            dimensions=self._strings(raw.get("dimensions")),
            filters=self._strings(raw.get("filters")),
            time_expressions=self._strings(raw.get("time_expressions")),
            operations=self._strings(raw.get("operations")),
        )
        if (
            re.search(r"SKU", original_query, re.IGNORECASE)
            and any(term in original_query for term in ("销售价", "标价", "定价"))
            and any(term in original_query for term in ("平均", "均值", "均价"))
            and any(term in original_query for term in ("店铺", "大区", "地区", "区域"))
        ):
            retrieval.retrieval_terms = list(
                dict.fromkeys(
                    [
                        *retrieval.retrieval_terms,
                        "SKU销售价",
                        "商品主表",
                        "店铺所属大区",
                    ]
                )
            )
        return PreparedRequest(
            action="database_query",
            confidence=confidence,
            reason=reason,
            standalone_query=standalone,
            # 是否发生上下文改写必须由实际文本决定，不能完全信任模型的布尔标记。
            rewritten=(
                bool(payload.get("rewritten"))
                or standalone != original_query.strip()
            ),
            retrieval=retrieval,
        )

    @staticmethod
    def _strings(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))

    @staticmethod
    def _ambiguous_regional_average_price(
        query: str, recent_context: str
    ) -> PreparedRequest | None:
        """将高风险的同名指标/维度歧义稳定转换为业务口径选择。"""
        current = query.strip()
        contextual = f"{current} {recent_context}".strip()
        has_average_price = bool(
            re.search(r"平均\s*(?:单价|价格)|(?:单价|价格)\s*(?:均值|平均)|均价", current)
        )
        has_region = bool(re.search(r"地区|大区|区域", contextual))
        has_source = bool(
            re.search(
                r"订单|成交|实付|店铺|SKU|商品标价|销售价|购物车|意向|用户画像|供应商|采购|成本",
                current,
                re.IGNORECASE,
            )
        )
        if not (has_average_price and has_region) or has_source:
            return None
        return PreparedRequest(
            action="database_query",
            confidence=1.0,
            reason="平均单价和地区在数据中存在多种业务口径，需要用户确认",
            standalone_query=current,
            rewritten=False,
            retrieval=RetrievalIntent(
                retrieval_terms=["平均单价", "地区"],
                metrics=["平均单价"],
                dimensions=["地区"],
                operations=["平均", "分组"],
            ),
            source="deterministic_business_guard",
            clarification={
                "parameter": "average_price_definition",
                "question": "你希望按哪种业务口径查看各地区的平均单价？",
                "reason": "不同价格和地区归属会产生不同结果",
                "options": [
                    {
                        "id": "order_region_actual_unit_price",
                        "label": "订单实际成交平均单价",
                        "description": "按订单所属大区统计已成交商品的实际单价",
                        "recommended": True,
                    },
                    {
                        "id": "store_region_list_price",
                        "label": "店铺SKU销售标价平均值",
                        "description": "按店铺所属大区统计SKU销售标价",
                        "recommended": False,
                    },
                    {
                        "id": "user_region_cart_unit_price",
                        "label": "用户购物车意向均价",
                        "description": "按用户画像地区统计购物车中的意向单价",
                        "recommended": False,
                    },
                ],
            },
        )
