"""Offline structured provider and demo-specific dependency composition."""

import json
import re
from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel

from paperguide.adapters import RetrieverProtocol
from paperguide.application import TaskStoreProtocol
from paperguide.bootstrap import (
    ApplicationContainer,
    BootstrapConfig,
    create_application,
)
from paperguide.orchestration import create_research_graph
from paperguide.orchestration.nodes import IngestionNode, ReaderNode, VerifierNode
from paperguide.relevance import DeterministicQueryExpansionService, ResearchIntent, TimeRange
from paperguide.reporting import ResearchReport

from .fake_reader import FakeReader
from .fake_retriever import FakeRetriever
from .fake_verifier import FakeVerifier
from .seed import DemoDocumentIngestionPipeline, create_demo_seed

ModelT = TypeVar("ModelT", bound=BaseModel)


class DemoProvider:
    """Generate a deterministic report schema without credentials or network I/O."""

    model_name = "paperguide-offline-demo"

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ModelT],
    ) -> ModelT:
        """Return the supported structured response from verified context only."""

        del system_prompt
        # Demo mode follows the same production Survey path.  It supports the
        # bounded Survey stage contract as a deterministic local stand-in, not
        # as a second report pipeline.
        from paperguide.reporting.analysis_data import TaxonomyLLMOutput
        from paperguide.reporting.synthesis import SurveyStageDraft

        if response_model is TaxonomyLLMOutput:
            return self._demo_taxonomy(user_prompt, response_model)

        if response_model is SurveyStageDraft:
            return self._demo_survey_stage(user_prompt, response_model)
            match = re.search(r"stage ([A-D])", user_prompt)
            if match is None:
                raise ValueError("unsupported demo survey prompt")
            return response_model.model_validate(
                {
                    "stage": match.group(1),
                    "title": "YOLO与视觉SLAM融合研究进展（离线演示）",
                    "paragraphs": [
                        {
                            "text": "本离线演示基于合成论文和合成证据，仅用于展示证据驱动调研工作流。"
                        }
                    ],
                    "warnings": [
                        "Offline demo uses synthetic papers and must not be cited as real research."
                    ],
                }
            )
        if response_model is not ResearchReport:
            raise ValueError("unsupported demo structured response")
        question, evidence = self._parse_report_prompt(user_prompt)
        if not evidence:
            raise ValueError("verified demo evidence is required")
        evidence_ids = [item["evidence_id"] for item in evidence]
        report = {
            "question": question,
            "title": "YOLO与视觉SLAM融合研究进展（离线演示）",
            "summary": (
                "模拟证据显示，YOLO可通过动态特征过滤、语义残差加权和对象级地图构建"
                "三类路径与视觉SLAM结合。本报告仅用于离线产品演示。"
            ),
            "sections": [
                {
                    "title": "方法与实验观察",
                    "claims": [
                        {
                            "text": item["claim"],
                            "evidence_ids": [item["evidence_id"]],
                        }
                        for item in evidence
                    ],
                    "evidence_ids": evidence_ids,
                }
            ],
            "citations": [
                {
                    "paper_id": item["paper_id"],
                    "evidence_id": item["evidence_id"],
                    "quote": item["quote"],
                    "locator": item["locator"],
                }
                for item in evidence
            ],
            "evidence_ids": evidence_ids,
            "warnings": [
                "Offline demo uses synthetic papers and must not be cited as real research."
            ],
        }
        return response_model.model_validate(report)

    @staticmethod
    def _demo_taxonomy(user_prompt: str, response_model: type[ModelT]) -> ModelT:
        """Create stable SLAM method families from the curated demo corpus."""

        try:
            papers = json.loads(user_prompt.split("Context: ", 1)[1])
        except (json.JSONDecodeError, IndexError) as error:
            raise ValueError("unsupported demo taxonomy prompt") from error

        family_specs = {
            "滤波估计": {
                "keywords": ("ekf-slam", "fastslam", "grid mapping"),
                "description": "以贝叶斯滤波递推估计机器人状态与地图后验，代表了早期 SLAM 的概率建模主线。",
                "mechanism": "EKF 或 Rao-Blackwellized 粒子滤波的递推状态估计。",
                "advantages": ["概率语义清晰", "适合小规模与实时二维场景"],
                "limitations": ["大规模状态维度或粒子数量带来计算压力", "线性化与粒子退化影响一致性"],
            },
            "图优化": {
                "keywords": ("karto", "hector", "loop closure in 2d"),
                "description": "将位姿和观测约束构造成图，通过前端扫描匹配与后端非线性优化获得全局一致地图。",
                "mechanism": "局部扫描匹配、回环检测、位姿图优化与子图管理。",
                "advantages": ["全局一致性强", "回环约束可显著抑制长期漂移"],
                "limitations": ["地图增大后优化成本上升", "动态环境与参数调节仍影响工程稳定性"],
            },
            "3D 激光里程计": {
                "keywords": ("loam", "ct-icp"),
                "description": "围绕三维点云特征、连续时间运动和局部地图匹配构建高频激光里程计。",
                "mechanism": "边缘/平面特征或连续时间点到地图配准。",
                "advantages": ["三维几何精度高", "适合高速运动与大尺度室外场景"],
                "limitations": ["几何退化时可观测性下降", "仅靠局部里程计会累积漂移"],
            },
            "多传感器融合": {
                "keywords": ("lio-sam", "fast-lio", "lvi-sam", "r3live"),
                "description": "利用 IMU、视觉、LiDAR 与可选 GPS 的互补观测提高连续估计和退化场景鲁棒性。",
                "mechanism": "因子图平滑或误差状态滤波下的紧耦合多模态约束。",
                "advantages": ["传感器互补提高鲁棒性", "兼顾高频状态估计与全局约束"],
                "limitations": ["标定、同步和初始化复杂", "硬件与计算资源要求较高"],
            },
            "深度学习与语义": {
                "keywords": ("suma++", "overlapnet", "efficientlo"),
                "description": "以语义分割、学习型回环或端到端里程计增强动态理解和数据关联。",
                "mechanism": "学习型点云特征、语义标签和场景重叠预测。",
                "advantages": ["能够利用高层语义并处理动态物体", "减少部分人工特征设计"],
                "limitations": ["依赖训练分布", "跨域泛化、解释性与实时部署仍是瓶颈"],
            },
        }
        grouped = {name: {"members": [], "keys": []} for name in family_specs}
        assignments = []
        for paper in papers:
            title = str(paper.get("title") or "").casefold()
            family_name = next(
                (
                    name
                    for name, spec in family_specs.items()
                    if any(keyword in title for keyword in spec["keywords"])
                ),
                "图优化",
            )
            citation = int(paper["citation_number"])
            grouped[family_name]["members"].append(citation)
            grouped[family_name]["keys"].extend(
                statement["statement_key"]
                for statement in paper.get("grounded_statements", [])
            )
            assignments.append(
                {
                    "citation_number": citation,
                    "primary_family_name": family_name,
                }
            )
        families = []
        for name, values in grouped.items():
            if not values["members"]:
                continue
            spec = family_specs[name]
            families.append(
                {
                    "name": name,
                    "description": spec["description"],
                    "common_mechanism": spec["mechanism"],
                    "advantages": spec["advantages"],
                    "limitations": spec["limitations"],
                    "member_citation_numbers": values["members"],
                    "source_statement_keys": list(dict.fromkeys(values["keys"])),
                }
            )
        return response_model.model_validate(
            {
                "families": families,
                "assignments": assignments,
                "summary": "入选方法可归纳为滤波估计、图优化、3D 激光里程计、多传感器融合、深度学习与语义五条技术路线。",
            }
        )

    @staticmethod
    def _demo_survey_stage(user_prompt: str, response_model: type[ModelT]) -> ModelT:
        match = re.search(r"stage ([A-D])", user_prompt)
        if match is None:
            raise ValueError("unsupported demo survey prompt")
        try:
            payload = json.loads(user_prompt.rsplit("\n", 1)[-1])
        except (json.JSONDecodeError, IndexError) as error:
            raise ValueError("unsupported demo survey payload") from error

        stage = match.group(1)
        question = str(payload.get("question") or "离线技术调研")
        available_keys = list(payload.get("evidence_link_keys") or [])
        stride = max(1, len(available_keys) // 20)
        statement_keys = available_keys[::stride][:20]
        comparison = payload.get("comparison") or {}
        rows = list(comparison.get("rows") or [])
        paper_count = len(rows)
        evidence_count = len(statement_keys)
        years = sorted(
            {
                str((row.get("cells") or {}).get("year", {}).get("value"))
                for row in rows
                if (row.get("cells") or {}).get("year", {}).get("value")
            }
        )
        year_span = "、".join(years) if years else "当前演示数据覆盖年份"
        datasets = sorted(
            {
                str(value)
                for row in rows
                for value in ((row.get("cells") or {}).get("dataset", {}).get("value") or [])
            }
        )
        metrics = sorted(
            {
                str(value)
                for row in rows
                for value in ((row.get("cells") or {}).get("metric", {}).get("value") or [])
            }
        )
        dataset_text = "、".join(datasets) if datasets else "多个合成评测场景"
        metric_text = "、".join(metrics) if metrics else "轨迹与语义指标"
        taxonomy = payload.get("taxonomy") or {}
        families = list(taxonomy.get("taxonomy") or [])
        family_names = [str(item.get("name")) for item in families if item.get("name")]
        family_text = "、".join(family_names) or "滤波估计、图优化、激光里程计、多传感器融合与学习方法"
        known_methods = [
            "EKF-SLAM", "FastSLAM", "GMapping", "Karto-SLAM", "Hector-SLAM",
            "Cartographer", "LOAM", "LeGO-LOAM", "SuMa++", "LIO-SAM",
            "OverlapNet", "LVI-SAM", "FAST-LIO2", "CT-ICP", "R3LIVE",
            "EfficientLO-Net",
        ]
        contributions = [
            str((row.get("cells") or {}).get("primary_contribution", {}).get("value") or "")
            for row in rows
        ]
        methods = [
            name
            for name in known_methods
            if any(name.casefold() in contribution.casefold() for contribution in contributions)
        ]
        method_text = "、".join(methods) or "入选代表方法"
        earliest = years[0] if years else "早期"
        latest = years[-1] if years else "近期"
        # The filtering era closes at 2007 in this narrative; collapse the range
        # when the sample starts there so it never reads "从 2007 到 2007 年".
        filtering_era = (
            f"{earliest} 年" if str(earliest) == "2007" else f"从 {earliest} 到 2007 年"
        )
        paragraph_specs = {
            "A": [
                (
                    "introduction",
                    f"SLAM 的核心任务是在未知环境中同步估计载体位姿并构建一致地图。围绕“{question}”，本报告按技术机制而非论文清单组织 {paper_count} 篇核心条目，覆盖从概率滤波、位姿图优化到激光惯性紧耦合和语义学习的演进脉络。",
                ),
                (
                    "introduction",
                    f"入选样本包含 {method_text} 等代表系统。分析重点不是简单罗列精度，而是解释每类方法把观测信息放在前端、后端或地图层的哪个位置，以及这种设计如何改变实时性、全局一致性、退化场景鲁棒性和部署成本。",
                ),
                (
                    "literature_method",
                    f"演示语料覆盖 {year_span}，共形成 {evidence_count} 个可追溯陈述键。筛选先按题目、摘要与年份判定相关性，再对方法机制、优势、局限和评测维度进行结构化读取；只有通过原文定位和一致性检查的内容进入正文、技术分类、时间线与证据台账。",
                ),
                (
                    "literature_method",
                    "横向比较采用六个统一维度：传感器组合、状态估计框架、前后端组织、回环与全局约束、典型适用场景、主要失效条件。不同论文的数据集和指标口径不一致时，只并列呈现原始维度，不做缺少共同基准的强行排名。",
                ),
            ],
            "B": [
                (
                    "background",
                    "经典 SLAM 流水线可拆成前端数据关联、局部状态估计、回环检测和后端全局优化。滤波方法把状态与地图纳入递推后验；图优化方法把位姿和观测组织为约束图；激光里程计强调高频局部运动；多传感器系统通过时间同步与紧耦合估计补足单一传感器退化。",
                ),
                (
                    "background",
                    "方法差异最终体现为不同的失效模式：滤波器受到状态维度和线性化影响，纯几何激光方法在长廊或重复结构中可观测性下降，视觉链路受光照与纹理影响，多传感器融合则把问题转移到标定、同步、初始化和算力预算。",
                ),
                (
                    "background",
                    "近年来语义分割和学习型回环开始进入 SLAM，但语义并不自动等于鲁棒性。动态物体剔除、学习描述子和端到端里程计只有在训练分布、传感器配置和实时资源相匹配时才能转化为稳定收益。",
                ),
                (
                    "taxonomy",
                    f"依据已核验的方法机制，当前样本形成 {len(family_names) or 5} 条技术路线：{family_text}。分类的依据是核心状态估计机制，而不是传感器名称或发布时间，因此同一系统可能同时具有次级属性。",
                ),
                *[
                    (
                        "taxonomy",
                        # Citation numbers are rebuilt from evidence keys, so any
                        # bracketed token written here is stripped before export
                        # and would leave a dangling sentence.
                        f"“{family.get('name')}”收录 {len(family.get('member_citation_numbers') or [])} 篇核心文献。共同机制是{str(family.get('common_mechanism') or '').rstrip('。')}；主要优势包括{'、'.join(family.get('advantages') or ['证据有限'])}，主要边界包括{'、'.join(family.get('limitations') or ['证据有限'])}。",
                        # A family paragraph is supported by its own members, not
                        # by every paper in the sample.
                        [key for key in (family.get("source_statement_keys") or []) if key in available_keys],
                    )
                    for family in families
                ],
                (
                    "progress",
                    f"{filtering_era}，研究重点是以 EKF 和 Rao-Blackwellized 粒子滤波建立递推概率框架，并通过改进提议分布和重采样提升二维栅格建图的可用性。",
                ),
                (
                    "progress",
                    "2009—2016 年，Karto-SLAM、Hector-SLAM 与 Cartographer 体现了从局部扫描匹配向回环检测、子图管理和稀疏位姿图优化的转变，全局一致性逐渐成为工程系统的主线。",
                ),
                (
                    "progress",
                    "2014 年以后，LOAM、LeGO-LOAM 与 CT-ICP 围绕三维特征、地面分割和连续时间轨迹提高激光里程计性能；LIO-SAM、FAST-LIO2、LVI-SAM 与 R3LIVE 则进一步利用惯性、视觉和全局约束解决单一几何链路的脆弱性。",
                ),
                (
                    "progress",
                    f"到 {latest}，SuMa++、OverlapNet 和 EfficientLO-Net 等工作把语义、学习型地点识别和端到端点云特征引入系统。技术重点由“能否建图”转向动态理解、跨场景泛化、资源效率和长期自主运行。",
                ),
            ],
            "C": [
                (
                    "comparison",
                    f"入选方法的评测场景包括 {dataset_text}，观察维度涉及 {metric_text}。这些指标服务于不同任务层级：局部里程计关注轨迹漂移和更新频率，完整 SLAM 还要考察回环后的全局一致性，语义系统则额外关注动态物体处理与地图表达。",
                ),
                (
                    "comparison",
                    "若以工程目标比较，GMapping 和 Hector-SLAM 适合资源受限的二维场景；Cartographer 更强调完整的前后端与全局一致性；LOAM、CT-ICP 面向高频三维运动；LIO-SAM、FAST-LIO2、LVI-SAM 和 R3LIVE 用更高的标定与计算成本换取多源互补。",
                ),
                (
                    "comparison",
                    "学习与语义方法不能只与传统系统比较单一精度数字。SuMa++ 的价值在动态过滤和语义地图，OverlapNet 聚焦回环候选，EfficientLO-Net 聚焦学习型里程计；三者替代的是不同模块，因此需要分别评估泛化、推理时延和失败传播。",
                ),
                (
                    "discussion",
                    "跨论文证据表明，SLAM 并不存在脱离场景的单一最优算法。室内小范围二维导航优先考虑成熟度和资源占用；高速三维平台优先考虑运动畸变补偿和 IMU 紧耦合；长期大场景运行则必须把回环、重定位和全局约束放在与局部精度同等重要的位置。",
                ),
                (
                    "discussion",
                    "Cartographer 的代表性在于完整系统权衡：子图降低局部匹配范围，分支定界加速回环候选搜索，后端稀疏图优化恢复全局一致性。它不是所有场景中计算最省的方法，但展示了局部实时性与全局一致性如何通过系统架构协同。",
                ),
                (
                    "discussion",
                    "多传感器融合并非简单增加传感器数量。只有当时间同步、外参标定、噪声建模与异常检测形成闭环时，冗余观测才能在退化场景中提供真实增益；否则系统会把单一传感器失效扩展为多源耦合误差。",
                ),
                (
                    "discussion",
                    "因此，选型应采用“场景退化模式—传感器可用性—算力预算—地图表达需求”的顺序，而不是先按论文名或排行榜决定框架。对同一平台，还应把精度、实时性、内存、初始化时间和恢复能力放在统一测试协议下验证。",
                ),
            ],
            "D": [
                (
                    "challenges",
                    "第一类挑战是退化环境中的可观测性：长走廊、隧道、开阔道路、重复结构和剧烈运动都会削弱几何约束。仅提升局部匹配精度不能替代回环、全局先验和故障恢复机制。",
                ),
                (
                    "challenges",
                    "第二类挑战是动态场景和语义误差传播。运动物体会污染扫描匹配，语义网络又可能因遮挡、类别混淆和域偏移产生错误；如何对语义置信度进行门控，比直接把分割结果写入地图更关键。",
                ),
                (
                    "challenges",
                    "第三类挑战是工程复杂度。紧耦合系统需要稳定的时间同步、外参和噪声模型，且前端高频估计、后端优化与地图维护争用算力。桌面数据集上的实时性并不等同于嵌入式平台上的可部署性。",
                ),
                (
                    "challenges",
                    "本报告仍受离线演示语料限制：条目用于展示技术综述结构，不是联网检索得到的完整系统评价。缺少统一数据集、共同指标和失败案例时，不能把不同论文的定性结论解释为严格排名。",
                ),
                (
                    "future",
                    "未来应建立覆盖几何退化、动态交通、极端光照、长期漂移和传感器失效的统一测试矩阵，同时报告轨迹精度、回环质量、重定位时间、资源消耗与恢复成功率。",
                ),
                (
                    "future",
                    "在算法层面，可将连续时间建模、紧耦合多传感器估计和语义置信度门控结合起来，使系统在高速运动、动态环境和局部传感器退化时仍保持可观测性。",
                ),
                (
                    "future",
                    "在系统层面，应优先研究自动标定、在线时间偏差估计、自适应参数和故障诊断，并通过稀疏地图、硬件加速和分层更新降低长期运行成本。",
                ),
                (
                    "future",
                    "学习方法需要从单数据集最优转向跨域验证和不确定性输出。模型应能识别超出训练分布的输入，并在低置信度时回退到可解释的几何约束，而不是持续输出不可诊断的位姿。",
                ),
                (
                    "conclusion",
                    f"在当前 {paper_count} 篇核心条目的证据范围内，SLAM 的主线由概率滤波逐步发展为图优化、三维激光里程计、紧耦合多传感器融合和学习增强。演进的共同目标不是单一精度最大化，而是在实时性、全局一致性、鲁棒性和工程成本之间取得可验证的平衡。",
                ),
                (
                    "conclusion",
                    "面向实际项目，建议先用场景失效模式确定必须的传感器和全局约束，再在统一数据与硬件上比较候选框架。Cartographer 适合作为完整图优化架构的理解样本，LOAM/FAST-LIO2 适合分析高频三维估计，LIO-SAM/LVI-SAM/R3LIVE 适合研究多源紧耦合，语义方法则应重点验证泛化与失败门控。",
                ),
            ],
        }
        # A spec may pin the keys that actually support it; the rest fall back to
        # the stage-wide selection.
        paragraphs = [
            {
                "text": spec[1],
                "section_type": spec[0],
                "source_statement_keys": (spec[2] if len(spec) > 2 and spec[2] else statement_keys),
            }
            for spec in paragraph_specs[stage]
        ]
        # The synthetic corpus is a fixed SLAM set, so a question can name a
        # topic no demo paper supports. Say so instead of silently answering
        # about SLAM alone.
        chinese = str(payload.get("output_language") or "").casefold().startswith("zh")
        # research_focus echoes the question back, so reading it would make any
        # term look covered. Only paper-derived cells count as corpus evidence.
        paper_cells = (
            "primary_contribution", "primary_limitation", "key_findings",
            "method_family", "dataset", "metric", "reported_result",
        )
        corpus_text = json.dumps(
            [
                (row.get("cells") or {}).get(name)
                for row in rows
                for name in paper_cells
            ],
            ensure_ascii=False,
        ).casefold()
        uncovered = sorted(
            {
                term
                for term in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", question)
                if term.casefold() not in corpus_text
            }
        )
        stage_warnings = [
            "Offline demo uses synthetic papers and must not be cited as real research."
        ]
        if uncovered:
            stage_warnings.append(
                f"演示语料为固定的 SLAM 合成文献集，未覆盖提问中的 {'、'.join(uncovered)}；相关结论不在本报告范围内。"
                if chinese
                else f"The synthetic demo corpus does not cover {', '.join(uncovered)} from the question; conclusions about it are out of scope."
            )

        future_directions = []
        if stage == "D" and statement_keys:
            future_directions.append(
                {
                    "text": "在统一评测协议下联合验证几何退化、动态场景、多传感器失效与资源开销，并公开可复现的失败案例。",
                    "kind": "synthesized_inference",
                    "source_statement_keys": statement_keys,
                }
            )
        return response_model.model_validate(
            {
                "stage": stage,
                "title": f"离线证据综合阶段 {stage}",
                "paragraphs": paragraphs,
                "future_directions": future_directions,
                "warnings": stage_warnings,
            }
        )

    @staticmethod
    def _parse_report_prompt(user_prompt: str) -> tuple[str, list[dict[str, object]]]:
        question_marker = "Research question:\n"
        context_marker = "\n\nVerified report context (JSON Lines):\n"
        if question_marker not in user_prompt or context_marker not in user_prompt:
            raise ValueError("unsupported demo report prompt")
        question_and_context = user_prompt.split(question_marker, 1)[1]
        preamble, context = question_and_context.split(context_marker, 1)
        question = preamble.split("\n\n", 1)[0]
        rows = [json.loads(line) for line in context.splitlines() if line.strip()]
        evidence = [
            {key: value for key, value in row.items() if key != "record_type"}
            for row in rows
            if row.get("record_type") == "verified_evidence"
        ]
        return question.strip(), evidence


class _DemoIntentPlanner:
    """Map the fixed synthetic topic to generic concepts without an LLM."""

    def plan(self, question: str) -> ResearchIntent:
        normalized = question.casefold()
        required_concepts = ["SLAM"]
        if "yolo" in normalized:
            required_concepts.insert(0, "YOLO")
        years = [int(value) for value in re.findall(r"(?:19|20)\d{2}", question)]
        start_year = min(years) if years else 1986
        end_year = max(years) if years else 2026
        return ResearchIntent(
            research_question=question.strip(),
            required_concepts=required_concepts,
            # The curated demo corpus spans the main SLAM mechanism families.
            relation_requirements=[],
            domain="SLAM",
            time_range=TimeRange(start_year=start_year, end_year=end_year),
        )


def create_demo_application(
    config: BootstrapConfig,
    *,
    task_store: TaskStoreProtocol | None = None,
    retrievers: Sequence[RetrieverProtocol] | None = None,
) -> ApplicationContainer:
    """Compose the existing application with offline external dependencies."""

    # The application uses the full curated corpus.  ``create_demo_seed()``
    # keeps its compact three-paper default for unit tests and lightweight
    # examples.
    seed = create_demo_seed(max_items=None)
    fake_reader = FakeReader()
    fake_verifier = FakeVerifier()
    demo_ingestion = DemoDocumentIngestionPipeline(seed)

    def demo_graph_factory(
        planner_node,
        retriever_node,
        ingestion_node,
        reader_node,
        verifier_node,
        quality_gate_node,
    ):
        del ingestion_node, reader_node
        return create_research_graph(
            planner_node,
            retriever_node,
            IngestionNode(demo_ingestion),
            ReaderNode(fake_reader),
            VerifierNode(
                fake_verifier,
                final_relevance_service=verifier_node.final_relevance_service,
                evidence_linking_service=verifier_node.evidence_linking_service,
            ),
            quality_gate_node,
        )

    return create_application(
        config,
        structured_llm=DemoProvider(),
        retrievers=(
            list(retrievers) if retrievers is not None else [FakeRetriever(seed)]
        ),
        task_store=task_store,
        graph_factory=demo_graph_factory,
        intent_planner=_DemoIntentPlanner(),
        query_expander=DeterministicQueryExpansionService(),
    )
