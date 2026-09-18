# 标注复核清单

把下面任一节整段贴给大模型即可。判断标准只有一条：

> **如果一个做这个方向的人提出该问题，这篇论文没有被检索到，算不算漏了？**
> 算漏 → 该纳入；不算 → 不该纳入。

宁可少留几篇高置信度的，也不要把边缘的都算上。标注集是尺子，尺子本身得准。

---

## 一、多用户协作任务卸载与资源分配

**问题**：多用户协作任务卸载与资源分配

我的纳入依据：标题中出现协作 / 多用户 / 联合优化 / 资源分配 / D2D。
我的排除依据：属于任务卸载领域，但不涉及多用户协作或联合分配（综述、无人机场景、隐私侧重、单用户）。

### 我判定为「该纳入」（22 篇）

纳入 | 2020 | Collaborative Task Offloading for Overloaded Mobile Edge Computing in Small-Cell Networks
纳入 | 2023 | Reverse Auction-Based Computation Offloading and Resource Allocation in Mobile Cloud-Edge Computing
纳入 | 2023 | Joint Optimization of Computing Offloading and Service Caching in Edge Computing-Based Smart Grid
纳入 | 2020 | A Cyclic Game for Service-Oriented Resource Allocation in Edge Computing
纳入 | 2025 | A Nash Bargaining Cooperative Game Policy in Mobile Edge Computing
纳入 | 2017 | Partial Offloading for Latency Minimization in Mobile-Edge Computing
纳入 | 2022 | Joint Offloading and Resource Allocation With Partial Information for Multi-User Edge Computing
纳入 | 2021 | D2D-Assisted Multi-User Cooperative Partial Offloading, Transmission Scheduling and Computation Allocating for MEC
纳入 | 2023 | Task Co-Offloading for D2D-Assisted Mobile Edge Computing in Industrial Internet of Things
纳入 | 2025 | Incentive-Driven Task Offloading and Collaborative Computing in Device-Assisted MEC Networks
纳入 | 2023 | Incentive-Based Distributed Resource Allocation for Task Offloading and Collaborative Computing in MEC-Enabled Networks
纳入 | 2024 | MEC Network Slicing: Stackelberg-Game-Based Slice Pricing and Resource Allocation With QoS Guarantee
纳入 | 2024 | A Repeated Auction Model for Load-Aware Dynamic Resource Allocation in Multi-Access Edge Computing
纳入 | 2022 | Signaling-Based Incentive Mechanism for D2D Computation Offloading
纳入 | 2022 | Incentive-Driven Task Allocation for Collaborative Edge Computing in Industrial Internet of Things
纳入 | 2021 | Profit-Maximized Collaborative Computation Offloading and Resource Allocation in Distributed Cloud and Edge Computing Systems
纳入 | 2026 | Privacy-Protected Joint Service Placement and Task Offloading for Knowledge-Defined Cloud-Edge Networking
纳入 | 2025 | Quality of Experience and Reliability-Aware Task Offloading and Scheduling for Multi-User Mobile-Edge Computing Systems
纳入 | 2024 | Hybrid Deep Reinforcement Learning-Based Task Offloading for D2D-Assisted Cloud-Edge-Device Collaborative Networks
纳入 | 2023 | Multi-Agent DRL for Joint Completion Delay and Energy Consumption With Queuing Theory in MEC-Based IIoT
纳入 | 2024 | SAC-PP: Jointly Optimizing Privacy Protection and Computation Offloading for Mobile Edge Computing
纳入 | 2025 | Explainable Multiagent Deep Reinforcement Learning for Joint Task Offloading and Resource Allocation in Distance and Channel-Aware NOMA Vehicular Edge Networks

### 我判定为「不该纳入」（20 篇）

排除 | 2018 | Task Offloading for Mobile Edge Computing in Software Defined Ultra-Dense Network
排除 | 2017 | A Survey on Mobile Edge Computing: The Communication Perspective
排除 | 2023 | UAV-Aided Computation Offloading in Mobile-Edge Computing Networks: A Stackelberg Game Approach
排除 | 2024 | A Truthful Incentive Mechanism for Movement-Aware Task Offloading in Crowdsourced Mobile Edge Computing Systems
排除 | 2020 | Risk-Aware Data Offloading in Multi-Server Multi-Access Edge Computing Environment
排除 | 2024 | Location Privacy-Aware Task Offloading in Mobile Edge Computing
排除 | 2022 | Profit Maximization Incentive Mechanism for Resource Providers in Mobile Edge Computing
排除 | 2022 | TCDA: Truthful Combinatorial Double Auctions for Mobile Edge Computing in Industrial Internet of Things
排除 | 2026 | Personalized Location Privacy-Aware Task Offloading: A Dual-Agent DRL Approach
排除 | 2026 | Task Offloading With Differential Privacy in Multi-Access Edge Computing: An A3C-Based Approach
排除 | 2025 | Revisiting Location Privacy in MEC-Enabled Computation Offloading
排除 | 2025 | Energy-Privacy Tradeoff for Task Matching in Edge Computing Power Networks
排除 | 2025 | A Differential Privacy Based Task Offloading Algorithm for Vehicular Edge Computing
排除 | 2026 | An Entropy-Based Privacy-Preserving Federated Deep Reinforcement Learning Framework for Task Offloading in Vehicular Edge Computing Networks
排除 | 2025 | Latency and Reliability-Aware Dynamic Task Offloading and Scheduling for Energy-Harvesting Systems in Mobile Edge Computing
排除 | 2024 | A Game-Theoretic Approach-Based Task Offloading and Resource Pricing Method for Idle Vehicle Devices Assisted VEC
排除 | 2023 | Computation Offloading Method Using Stochastic Games for Software-Defined-Network-Based Multiagent Mobile Edge Computing
排除 | 2024 | Privacy-Preserving Offloading Scheme in Multi-Access Mobile Edge Computing Based on MADRL
排除 | 2024 | Combining Lyapunov Optimization With Actor--Critic Networks for Privacy-Aware IIoT Computation Offloading
排除 | 2022 | Physics-informed neural networks for non-Newtonian fluid thermo-mechanical problems: An application to rubber calendering process

---

## 二、动态环境下的视觉SLAM与语义建图

**问题**：动态环境下的视觉SLAM与语义建图研究进展

我的纳入依据：标题涉及视觉 / 语义 / 动态场景 / 回环 / RGB-D / 单目。
我的排除依据：同属 SLAM 但走激光、水下、嵌入式硬件等其他路线。

### 我判定为「该纳入」（15 篇）

纳入 | 2026 | A Robust and Efficient Visual-Inertial SLAM Using Hybrid Point-Line Features
纳入 | 2021 | RS-SLAM: A Robust Semantic SLAM in Dynamic Environments Based on RGB-D Sensor
纳入 | 2025 | DOG-SLAM: Enhancing Dynamic Visual SLAM Precision Through GMM-Based Dynamic Object Removal and ORB-Boost
纳入 | 2026 | HPGS-SLAM: Hybrid Point-Guided Dense Visual SLAM With Online Mapping via Gaussian Splatting
纳入 | 2026 | SDT-SLAM: A Short-Term Dynamic Tracking SLAM Algorithm for Dynamic Scenes Based on RGB-D Sensors
纳入 | 2026 | WaterSplat-SLAM: Photorealistic Monocular SLAM in Underwater Environment
纳入 | 2025 | RGBDS-SLAM: A RGB-D Semantic Dense SLAM Based on 3D Multi Level Pyramid Gaussian Splatting
纳入 | 2021 | RDMO-SLAM: Real-Time Visual SLAM for Dynamic Environments Using Semantic Label Prediction With Optical Flow
纳入 | 2025 | Depth Completion With Multiple Balanced Bases and Confidence for Dense Monocular SLAM
纳入 | 2024 | ObVi-SLAM: Long-Term Object-Visual SLAM
纳入 | 2025 | DMN-SLAM: Multi-MLPs Neural Implicit Representation SLAM for Dynamic Environments
纳入 | 2024 | PIPO-SLAM: Lightweight Visual-Inertial SLAM With Preintegration Merging Theory and Pose-Only Descriptions of Multiple View Geometry
纳入 | 2026 | IMGS-SLAM: Monocular Gaussian Splatting SLAM for Indoor Reconstruction
纳入 | 2025 | DFusion-SLAM: A Lightweight Semantic Fusion Framework for Robust Visual SLAM in Dynamic Environments
纳入 | 2024 | DynaQuadric: Dynamic Quadric SLAM for Quadric Initialization, Mapping, and Tracking

### 我判定为「不该纳入」（35 篇）

排除 | 2019 | HOOFR SLAM System: An Embedded Vision SLAM Algorithm and Its Hardware-Software Mapping-Based Intelligent Vehicles Applications
排除 | 2023 | Fast and Versatile Feature-Based LiDAR Odometry via Efficient Local Quadratic Surface Approximation
排除 | 2025 | PttAcc: Pipeline-Based Taylor Expansion Fitting Arctangent Angle Hardware Accelerator Design for Descriptor Duty in ORB-SLAM System
排除 | 2024 | $D^{2}$SLAM: Decentralized and Distributed Collaborative Visual-Inertial SLAM System for Aerial Swarm
排除 | 2026 | RP-SLAM: Real-Time Photorealistic SLAM With Efficient 3D Gaussian Splatting
排除 | 2026 | TGS-SLAM: Tri-Plane Gaussian Splatting for Semantic SLAM
排除 | 2020 | VPS-SLAM: Visual Planar Semantic SLAM for Aerial Robotic Systems
排除 | 2024 | Open-Structure: Structural Benchmark Dataset for SLAM Algorithms
排除 | 2020 | Structure-SLAM: Low-Drift Monocular SLAM in Indoor Environments
排除 | 2023 | Contour-SLAM: A Robust Object-Level SLAM Based on Contour Alignment
排除 | 2025 | Fast Inertial-Only SLAM: A Fast Pedestrian SLAM Method for Structured Buildings Based on Foot-Mounted IMU
排除 | 2025 | A Multi-AUV Collaborative Mapping System With Bathymetric Cooperative Active SLAM Algorithm
排除 | 2021 | OV$^{2}$SLAM: A Fully Online and Versatile Visual SLAM for Real-Time Applications
排除 | 2024 | EGLT-SLAM: Real-Time Visual-Inertial SLAM Based on Entropy-Guided Line Tracking
排除 | 2024 | Finite-Plane Simultaneous Localization and Mapping (FP-SLAM): A New RGB-D SLAM Exploiting Interfeature Relationship
排除 | 2025 | R4-SLAM: Toward Real-Time, Robust, and Resource-Restricted Visual SLAM in Dynamic Environments
排除 | 2022 | SO-SLAM: Semantic Object SLAM With Scale Proportional and Symmetrical Texture Constraints
排除 | 2015 | COP-SLAM: Closed-Form Online Pose-Chain Optimization for Visual SLAM
排除 | 2025 | DDN-SLAM: Real Time Dense Dynamic Neural Implicit SLAM
排除 | 2015 | DV-SLAM (Dual-Sensor-Based Vector-Field SLAM) and Observability Analysis
排除 | 2024 | BASL-AD SLAM: A Robust Deep-Learning Feature-Based Visual SLAM System With Adaptive Motion Model
排除 | 2024 | Hilti SLAM Challenge 2023: Benchmarking Single + Multi-Session SLAM Across Sensor Constellations in Construction
排除 | 2025 | CoVOR-SLAM: Cooperative SLAM Using Visual Odometry and Ranges for Multi-Robot Systems
排除 | 2025 | GRAND-SLAM: Local Optimization for Globally Consistent Large-Scale Multi-Agent Gaussian SLAM
排除 | 2020 | DeepFactors: Real-Time Probabilistic Dense Monocular SLAM
排除 | 2015 | ORB-SLAM: A Versatile and Accurate Monocular SLAM System
排除 | 2022 | UV-SLAM: Unconstrained Line-Based SLAM Using Vanishing Points for Structural Mapping
排除 | 2024 | SBC-SLAM: Semantic Bioinspired Collaborative SLAM for Large-Scale Environment Perception of Heterogeneous Systems
排除 | 2025 | LoC-WiFi-SLAM: Low-Complexity of WiFi-Enhanced SLAM
排除 | 2024 | TextSLAM: Visual SLAM With Semantic Planar Text Features
排除 | 2021 | RDS-SLAM: Real-Time Dynamic SLAM Using Semantic Segmentation Methods
排除 | 2017 | Visual-Inertial Monocular SLAM With Map Reuse
排除 | 2025 | NeuV-SLAM: Fast Neural Multiresolution Voxel Optimization for RGBD Dense SLAM
排除 | 2023 | UWB Radar SLAM: An Anchorless Approach in Vision Denied Indoor Environments
排除 | 2008 | Large-Scale SLAM Building Conditionally Independent Local Maps: Application to Monocular Vision
