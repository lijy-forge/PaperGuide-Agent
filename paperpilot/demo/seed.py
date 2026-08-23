"""Deterministic, copyright-safe seed data for the offline demonstration."""

from dataclasses import dataclass
from uuid import UUID, NAMESPACE_URL, uuid5

from paperpilot.document import (
    Document,
    DocumentIngestionResult,
    IngestionStatus,
    Page,
    PaperIngestionItem,
    Section,
)
from paperpilot.domain import (
    Author,
    FullTextStatus,
    PaperCandidate,
    PaperSource,
)

DEMO_QUESTION = "YOLO与视觉SLAM融合研究进展"


def _demo_uuid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://paperpilot.local/demo/{name}")


@dataclass(frozen=True, slots=True)
class DemoSeed:
    """Immutable collection of synthetic candidates and parsed documents."""

    papers: tuple[PaperCandidate, ...]
    documents: tuple[Document, ...]


_PAPER_DATA = (
    {
        "key": "ekf-slam",
        "title": "EKF-SLAM and the Probabilistic Foundation of Simultaneous Localization and Mapping",
        "authors": ("R. Smith", "M. Self", "P. Cheeseman"),
        "year": 1988,
        "abstract": "A curated offline overview of the extended Kalman filter formulation that established the probabilistic state-estimation foundation of SLAM.",
        "method": "EKF-SLAM jointly represents robot pose and landmark uncertainty and updates the state with linearized motion and observation models.",
        "experiment": "Its explicit covariance model makes uncertainty interpretable and works well for compact feature maps, but covariance updates grow quadratically with map size and repeated linearization can introduce inconsistency.",
        "method_name": "滤波估计｜EKF-SLAM",
        "dataset": "Feature-map scenarios",
        "metric": "state covariance and consistency",
        "metric_value": "qualitative method comparison",
        "baseline": "probabilistic localization and mapping",
        "advantage": "不确定性表达清晰，是后续概率 SLAM 的理论基础。",
        "limitation": "协方差更新复杂度随地图规模快速增长，线性化误差限制大规模应用。",
    },
    {
        "key": "fastslam",
        "title": "FastSLAM: A Factored Solution to the Simultaneous Localization and Mapping Problem",
        "authors": ("M. Montemerlo", "S. Thrun", "D. Koller", "B. Wegbreit"),
        "year": 2002,
        "abstract": "A curated offline overview of FastSLAM and its Rao-Blackwellized particle-filter decomposition of the SLAM posterior.",
        "method": "FastSLAM separates robot-path estimation from independent landmark estimation by combining particle filtering with per-landmark Kalman filters.",
        "experiment": "The factorization supports nonlinear motion models and reduces the cost of landmark updates, while particle depletion and the number of particles remain limiting factors in large or ambiguous environments.",
        "method_name": "滤波估计｜FastSLAM",
        "dataset": "Landmark-map scenarios",
        "metric": "particle efficiency",
        "metric_value": "qualitative method comparison",
        "baseline": "joint-state EKF-SLAM",
        "advantage": "将轨迹估计与地标估计分解，能够处理非线性与非高斯后验。",
        "limitation": "粒子退化和大场景粒子数量需求会显著增加内存与计算开销。",
    },
    {
        "key": "gmapping",
        "title": "Improved Techniques for Grid Mapping with Rao-Blackwellized Particle Filters",
        "authors": ("G. Grisetti", "C. Stachniss", "W. Burgard"),
        "year": 2007,
        "abstract": "A curated offline overview of the GMapping line of work for two-dimensional occupancy-grid SLAM.",
        "method": "GMapping improves the proposal distribution with scan matching and uses adaptive resampling to reduce the number of particles needed for grid mapping.",
        "experiment": "The approach became a practical real-time option for small indoor 2D maps, but performance depends on odometry and scan quality and it lacks an explicit modern pose-graph loop-closure backend.",
        "method_name": "滤波估计｜GMapping",
        "dataset": "Indoor 2D occupancy grids",
        "metric": "mapping stability and runtime",
        "metric_value": "qualitative method comparison",
        "baseline": "standard RBPF grid mapping",
        "advantage": "选择性重采样降低粒子需求，在小型室内二维建图中实时性较好。",
        "limitation": "依赖里程计和扫描质量，缺少显式全局回环优化，不适合超大场景。",
    },
    {
        "key": "karto-slam",
        "title": "Karto-SLAM: Pose-Graph Optimization for Two-Dimensional Laser Mapping",
        "authors": ("K. Konolige", "G. Grisetti", "R. Kümmerle"),
        "year": 2009,
        "abstract": "A curated offline overview of Karto-style pose-graph laser SLAM and correlation scan matching.",
        "method": "Karto-SLAM represents robot poses as graph nodes and scan constraints as edges, then performs nonlinear pose-graph optimization after loop closures.",
        "experiment": "The global graph formulation improves map consistency and supports loop closure, while repeated optimization and correlation search can reduce real-time performance as the map grows.",
        "method_name": "图优化｜Karto-SLAM",
        "dataset": "Indoor 2D laser scans",
        "metric": "global map consistency",
        "metric_value": "qualitative method comparison",
        "baseline": "filter-based 2D SLAM",
        "advantage": "支持回环约束与全局一致性优化，结构清晰。",
        "limitation": "地图增大后相关性搜索和图优化开销上升，实时性受限。",
    },
    {
        "key": "hector-slam",
        "title": "A Flexible and Scalable SLAM System with Full 3D Motion Estimation",
        "authors": ("S. Kohlbrecher", "O. von Stryk", "J. Meyer", "U. Klingauf"),
        "year": 2011,
        "abstract": "A curated offline overview of Hector-SLAM and high-resolution scan-to-map alignment without wheel odometry.",
        "method": "Hector-SLAM aligns laser scans directly to a multi-resolution occupancy grid with Gauss-Newton optimization and does not require wheel odometry.",
        "experiment": "Its low dependence on auxiliary sensors is attractive for lightweight robots, but the absence of a strong loop-closure mechanism makes long trajectories vulnerable to accumulated drift.",
        "method_name": "图优化｜Hector-SLAM",
        "dataset": "High-rate indoor laser scans",
        "metric": "scan-matching stability",
        "metric_value": "qualitative method comparison",
        "baseline": "odometry-dependent 2D SLAM",
        "advantage": "无需轮式里程计，适合高频雷达和轻量平台。",
        "limitation": "缺少强回环检测，长距离或低结构场景中容易累积漂移。",
    },
    {
        "key": "loam",
        "title": "LOAM: Lidar Odometry and Mapping in Real-time",
        "authors": ("J. Zhang", "S. Singh"),
        "year": 2014,
        "abstract": "A curated offline overview of LOAM, a landmark real-time three-dimensional LiDAR odometry and mapping framework.",
        "method": "LOAM extracts edge and planar features and separates high-rate odometry from lower-rate mapping to balance motion estimation speed and map accuracy.",
        "experiment": "The dual-thread architecture established a strong accuracy-efficiency baseline for 3D LiDAR odometry, but the original system has no complete loop-closure module and therefore accumulates drift on long routes.",
        "method_name": "3D激光里程计｜LOAM",
        "dataset": "3D LiDAR sequences",
        "metric": "odometry accuracy and runtime",
        "metric_value": "qualitative method comparison",
        "baseline": "scan-to-scan LiDAR odometry",
        "advantage": "高频里程计与低频建图双线程兼顾精度和实时性。",
        "limitation": "原始系统缺少完整回环检测，长距离运行会产生累计误差。",
    },
    {
        "key": "cartographer",
        "title": "Real-Time Loop Closure in 2D LIDAR SLAM",
        "authors": ("W. Hess", "D. Kohler", "H. Rapp", "D. Andor"),
        "year": 2016,
        "abstract": "A curated offline overview of Google Cartographer and its submap-based real-time loop-closure architecture.",
        "method": "Cartographer inserts scans into local submaps, uses scan matching in the frontend, and applies branch-and-bound loop-closure search plus sparse pose-graph optimization in the backend.",
        "experiment": "The submap architecture offers strong global consistency, practical 2D and 3D support, and mature engineering, but large maps require substantial computation and careful parameter tuning and dynamic scenes can still disturb scan matching.",
        "method_name": "图优化｜Cartographer",
        "dataset": "2D and 3D LiDAR mapping",
        "metric": "loop-closure precision and map consistency",
        "metric_value": "qualitative method comparison",
        "baseline": "conventional pose-graph SLAM",
        "advantage": "子图、分支定界回环与稀疏图优化结合，精度、鲁棒性和工程成熟度较均衡。",
        "limitation": "大规模建图资源消耗较高，参数较多，动态物体会干扰扫描匹配。",
    },
    {
        "key": "lego-loam",
        "title": "LeGO-LOAM: Lightweight and Ground-Optimized Lidar Odometry and Mapping on Variable Terrain",
        "authors": ("T. Shan", "B. Englot"),
        "year": 2018,
        "abstract": "A curated offline overview of LeGO-LOAM, which adapts the LOAM pipeline for lightweight ground vehicles.",
        "method": "LeGO-LOAM segments ground points before feature extraction and integrates loop closure to reduce computation for variable-terrain ground vehicles.",
        "experiment": "Ground-aware segmentation lowers computation and improves suitability for small unmanned vehicles, but performance depends on reliable ground extraction and degrades in terrain without a stable ground surface.",
        "method_name": "3D激光里程计｜LeGO-LOAM",
        "dataset": "Variable-terrain LiDAR sequences",
        "metric": "odometry accuracy and resource usage",
        "metric_value": "qualitative method comparison",
        "baseline": "LOAM",
        "advantage": "地面分割和轻量化设计降低计算量，并补充回环检测。",
        "limitation": "对地面结构假设敏感，非平坦或地面缺失场景性能下降。",
    },
    {
        "key": "suma-plus",
        "title": "SuMa++: Efficient LiDAR-based Semantic SLAM",
        "authors": ("X. Chen", "A. Milioto", "E. Palazzolo", "P. Giguère", "J. Behley", "C. Stachniss"),
        "year": 2019,
        "abstract": "A curated offline overview of SuMa++, which introduces semantic information into surfel-based LiDAR SLAM.",
        "method": "SuMa++ associates semantic labels with surfels and uses them to improve data association and reject moving objects during LiDAR mapping.",
        "experiment": "Semantic cues improve dynamic-scene map quality and enable semantic mapping, but segmentation errors propagate into localization and inference adds computation and domain dependence.",
        "method_name": "深度学习与语义｜SuMa++",
        "dataset": "SemanticKITTI-style LiDAR sequences",
        "metric": "trajectory and semantic map quality",
        "metric_value": "qualitative method comparison",
        "baseline": "geometry-only surfel SLAM",
        "advantage": "利用语义剔除动态物体，同时输出语义地图。",
        "limitation": "分割误差会传播到定位与建图，推理成本和跨域泛化仍受限制。",
    },
    {
        "key": "lio-sam",
        "title": "LIO-SAM: Tightly-coupled Lidar Inertial Odometry via Smoothing and Mapping",
        "authors": ("T. Shan", "B. Englot", "D. Meyers", "W. Wang", "C. Ratti", "D. Rus"),
        "year": 2020,
        "abstract": "A curated offline overview of LIO-SAM and tightly coupled LiDAR-inertial smoothing with factor graphs.",
        "method": "LIO-SAM combines IMU preintegration, LiDAR odometry, loop closures, and optional GPS constraints in a factor-graph smoothing framework.",
        "experiment": "The modular factor graph supports multiple global constraints and robust long-distance estimation, but performance still depends on calibration and initialization and can degrade in geometrically repetitive or feature-poor environments.",
        "method_name": "多传感器融合｜LIO-SAM",
        "dataset": "LiDAR-IMU outdoor sequences",
        "metric": "trajectory accuracy and drift",
        "metric_value": "qualitative method comparison",
        "baseline": "LiDAR-only odometry",
        "advantage": "因子图统一融合 IMU、激光、回环和可选 GPS 约束，便于长期运行。",
        "limitation": "依赖标定与初始化，在几何退化或重复结构场景中仍可能失效。",
    },
    {
        "key": "overlapnet",
        "title": "OverlapNet: Loop Closing for LiDAR-based SLAM",
        "authors": ("X. Chen", "T. Läbe", "A. Milioto", "T. Röhling", "J. Behley", "C. Stachniss"),
        "year": 2020,
        "abstract": "A curated offline overview of OverlapNet and learned place recognition for LiDAR loop closure.",
        "method": "OverlapNet converts LiDAR scans into range-image channels and jointly predicts scan overlap and relative yaw for loop-closure candidate detection.",
        "experiment": "The learned descriptor improves rotational robustness and does not require a precise initial pose, but generalization can deteriorate when sensor configuration or environment appearance differs from training data.",
        "method_name": "深度学习与语义｜OverlapNet",
        "dataset": "LiDAR place-recognition sequences",
        "metric": "loop recall and yaw error",
        "metric_value": "qualitative method comparison",
        "baseline": "hand-crafted LiDAR descriptors",
        "advantage": "同时预测重叠率和航向角，对旋转和较差初始位姿更鲁棒。",
        "limitation": "跨传感器、跨城市和环境突变时存在明显域偏移风险。",
    },
    {
        "key": "lvi-sam",
        "title": "LVI-SAM: Tightly-coupled Lidar-Visual-Inertial Odometry via Smoothing and Mapping",
        "authors": ("T. Shan", "B. Englot", "C. Ratti", "D. Rus"),
        "year": 2021,
        "abstract": "A curated offline overview of LVI-SAM and tightly coupled LiDAR-visual-inertial estimation.",
        "method": "LVI-SAM links a visual-inertial subsystem with a LiDAR-inertial subsystem through factor-graph smoothing so the sensing modalities can provide mutual initialization and constraints.",
        "experiment": "Sensor redundancy improves robustness when texture or geometry is temporarily weak, but the system demands accurate multi-sensor calibration, higher computation, and careful handling of rapid motion and severe lighting changes.",
        "method_name": "多传感器融合｜LVI-SAM",
        "dataset": "LiDAR-camera-IMU sequences",
        "metric": "trajectory accuracy and subsystem robustness",
        "metric_value": "qualitative method comparison",
        "baseline": "single-modality inertial SLAM",
        "advantage": "视觉、激光和惯性互补，在纹理或几何局部退化时可相互支撑。",
        "limitation": "多传感器标定复杂、计算资源高，快速运动和极端光照仍会影响精度。",
    },
    {
        "key": "fast-lio2",
        "title": "FAST-LIO2: Fast Direct LiDAR-inertial Odometry",
        "authors": ("W. Xu", "Y. Cai", "D. He", "J. Lin", "F. Zhang"),
        "year": 2022,
        "abstract": "A curated offline overview of FAST-LIO2 and direct tightly coupled LiDAR-inertial odometry.",
        "method": "FAST-LIO2 directly registers raw LiDAR points to an incrementally maintained map and uses an iterated error-state Kalman filter with an ikd-Tree map structure.",
        "experiment": "Direct point-to-map updates support high-rate estimation across multiple LiDAR patterns, while the method remains sensitive to calibration, initialization, severe geometric degeneration, and the absence of a full standalone global loop-closure layer.",
        "method_name": "多传感器融合｜FAST-LIO2",
        "dataset": "High-rate LiDAR-IMU sequences",
        "metric": "runtime and trajectory accuracy",
        "metric_value": "qualitative method comparison",
        "baseline": "feature-based LiDAR-inertial odometry",
        "advantage": "直接处理原始点云并使用 ikd-Tree 增量地图，兼顾高频率和精度。",
        "limitation": "仍依赖精确标定和初始化，强退化场景需要额外全局约束。",
    },
    {
        "key": "ct-icp",
        "title": "CT-ICP: Real-time Elastic LiDAR Odometry with Loop Closure",
        "authors": ("P. Dellenbach", "J.-E. Deschaud", "B. Jacquet", "F. Goulette"),
        "year": 2022,
        "abstract": "A curated offline overview of continuous-time ICP for elastic LiDAR odometry under rapid motion.",
        "method": "CT-ICP models the scanner trajectory continuously within each LiDAR frame and optimizes point-to-map constraints to compensate motion distortion.",
        "experiment": "Continuous-time estimation improves robustness to aggressive motion and nonuniform scanning, but performance depends on reliable local geometry and the optimization and loop-closure configuration adds engineering complexity.",
        "method_name": "3D激光里程计｜CT-ICP",
        "dataset": "High-dynamics LiDAR sequences",
        "metric": "trajectory drift under motion distortion",
        "metric_value": "qualitative method comparison",
        "baseline": "rigid-frame ICP odometry",
        "advantage": "连续时间轨迹建模可补偿帧内运动畸变，对快速运动更稳健。",
        "limitation": "依赖局部几何可观测性，优化与回环配置增加工程复杂度。",
    },
    {
        "key": "r3live",
        "title": "R3LIVE: A Robust, Real-time, RGB-colored, LiDAR-Inertial-Visual Tightly-coupled State Estimation and Mapping Package",
        "authors": ("J. Lin", "F. Zhang"),
        "year": 2022,
        "abstract": "A curated offline overview of R3LIVE and real-time RGB-colored LiDAR-inertial-visual mapping.",
        "method": "R3LIVE tightly couples LiDAR-inertial geometry with visual photometric residuals to estimate motion and construct globally consistent RGB-colored point maps.",
        "experiment": "Photometric and geometric constraints provide rich colored maps and complementary state estimation, but computation, exposure variation, camera calibration, and hardware synchronization complicate lightweight deployment.",
        "method_name": "多传感器融合｜R3LIVE",
        "dataset": "LiDAR-camera-IMU color mapping",
        "metric": "trajectory and photometric map quality",
        "metric_value": "qualitative method comparison",
        "baseline": "LiDAR-inertial mapping",
        "advantage": "几何与光度约束联合估计，可实时构建高质量 RGB 彩色点云地图。",
        "limitation": "计算和同步成本较高，对曝光变化、相机标定和硬件配置较敏感。",
    },
    {
        "key": "efficientlo-net",
        "title": "EfficientLO-Net: Lightweight Deep LiDAR Odometry for Real-time Deployment",
        "authors": ("PaperPilot Curated Demo Team",),
        "year": 2023,
        "abstract": "A curated offline overview of efficient end-to-end learning for LiDAR odometry; bibliographic details remain intentionally bounded in demo mode.",
        "method": "EfficientLO-Net-style systems learn hierarchical point-cloud features and regress frame-to-frame motion in a compact end-to-end LiDAR odometry pipeline.",
        "experiment": "Learned feature extraction can approach classical LiDAR odometry accuracy with a streamlined pipeline, but training-data dependence, compute demand, explainability, and out-of-distribution robustness remain deployment barriers.",
        "method_name": "深度学习与语义｜EfficientLO-Net",
        "dataset": "Learned LiDAR odometry benchmarks",
        "metric": "trajectory accuracy and inference cost",
        "metric_value": "qualitative method comparison",
        "baseline": "classical feature-based LiDAR odometry",
        "advantage": "端到端特征学习简化传统人工模块，并兼顾较高的推理效率。",
        "limitation": "依赖训练分布，资源消耗、可解释性和跨域鲁棒性仍是落地障碍。",
    },
)


def create_demo_seed(max_items: int | None = 3) -> DemoSeed:
    """Build fresh deep-copy-safe seed objects with stable identifiers."""

    papers: list[PaperCandidate] = []
    documents: list[Document] = []
    selected = _PAPER_DATA if max_items is None else _PAPER_DATA[:max_items]
    for index, item in enumerate(selected, start=1):
        paper_id = _demo_uuid(item["key"])
        title = str(item["title"])
        paper = PaperCandidate(
            id=paper_id,
            title=title,
            normalized_title=title.casefold(),
            # Keep the broad SLAM concept explicit for deterministic metadata
            # gating even when a landmark system's official title says only
            # "odometry" or "mapping".
            abstract=f"SLAM survey context. {item['abstract']}",
            authors=[
                Author(
                    full_name=name,
                    normalized_name=name.casefold(),
                    affiliations=["PaperPilot Demo Lab"],
                )
                for name in item["authors"]
            ],
            publication_year=int(item["year"]),
            venue="PaperPilot Offline Demo Proceedings",
            arxiv_id=f"demo.{index:04d}",
            sources=[PaperSource.ARXIV],
            landing_page_url=f"https://example.invalid/demo/{item['key']}",
            pdf_url=f"https://example.invalid/demo/{item['key']}.pdf",
            citation_count=index * 7,
            full_text_status=FullTextStatus.AVAILABLE,
            relevance_score=1.0 - ((index - 1) * 0.05),
            selection_reason="Deterministic offline demonstration candidate.",
        )
        method_text = str(item["method"])
        experiment_text = str(item["experiment"])
        advantage_text = str(item["advantage"])
        limitation_text = f"本研究的局限：{item['limitation']}"
        page_text = (
            f"1 Introduction\n{paper.abstract}\n\n"
            f"2 Method\n{method_text}\n\n"
            f"3 Comparative assessment\n{experiment_text}\n\n"
            f"4 Strengths and limitations\n{advantage_text}\n{limitation_text}\n"
        )
        documents.append(
            Document(
                id=_demo_uuid(f"{item['key']}-document"),
                paper_id=paper_id,
                title=title,
                source_path=f"demo://{item['key']}.pdf",
                pages=[Page(page_number=1, text=page_text)],
                sections=[
                    Section(
                        title="Introduction",
                        page_start=1,
                        page_end=1,
                        text=str(item["abstract"]),
                    ),
                    Section(
                        title="Method",
                        page_start=1,
                        page_end=1,
                        text=method_text,
                    ),
                    Section(
                        title="Experiments",
                        page_start=1,
                        page_end=1,
                        text=experiment_text,
                    ),
                    Section(
                        title="Strengths and limitations",
                        page_start=1,
                        page_end=1,
                        text=f"{advantage_text}\n{limitation_text}",
                    ),
                ],
                metadata={
                    "demo": True,
                    "method_name": item["method_name"],
                    "method_quote": method_text,
                    "experiment_quote": experiment_text,
                    "dataset": item["dataset"],
                    "metric": item["metric"],
                    "metric_value": item["metric_value"],
                    "baseline": item["baseline"],
                    "advantage": item["advantage"],
                    "limitation": limitation_text,
                    "rich_demo": max_items is None,
                },
            )
        )
        papers.append(paper)
    return DemoSeed(papers=tuple(papers), documents=tuple(documents))


class DemoDocumentIngestionPipeline:
    """Offline document source satisfying the existing ingestion-node contract."""

    def __init__(self, seed: DemoSeed) -> None:
        self._documents = {document.paper_id: document for document in seed.documents}

    def ingest(self, papers: list[PaperCandidate]) -> DocumentIngestionResult:
        """Return seeded parsed documents without network or filesystem access."""

        items: list[PaperIngestionItem] = []
        documents: list[Document] = []
        for paper in papers:
            document = self._documents.get(paper.id)
            if document is None:
                items.append(
                    PaperIngestionItem(
                        paper_id=paper.id,
                        title=paper.title,
                        status=IngestionStatus.FAILED,
                        error_stage="demo_seed",
                        error_type="DemoDocumentNotFoundError",
                        error_message="demo document is unavailable",
                    )
                )
                continue
            copied = document.model_copy(deep=True)
            documents.append(copied)
            items.append(
                PaperIngestionItem(
                    paper_id=paper.id,
                    title=paper.title,
                    status=IngestionStatus.PARSED,
                    document=copied,
                    downloaded_file_path=copied.source_path,
                    content_hash=_demo_uuid(f"{paper.id}-content").hex * 2,
                    size_bytes=len(copied.pages[0].text.encode("utf-8")),
                    page_count=len(copied.pages),
                    warnings=["Synthetic offline demo document."],
                )
            )
        failed = sum(item.status is IngestionStatus.FAILED for item in items)
        return DocumentIngestionResult(
            items=items,
            documents=documents,
            total_requested=len(items),
            total_eligible=len(items),
            total_downloaded=len(documents),
            total_parsed=len(documents),
            total_skipped=0,
            total_failed=failed,
            warnings=["Demo mode uses synthetic documents and performs no downloads."],
        )
