# 标注复核清单

把下面任一节整段贴给大模型即可。判断标准只有一条：

> **如果一个做这个方向的人提出该问题，这篇论文没有被检索到，算不算漏了？**
> 算漏 → 该纳入；不算 → 不该纳入。

宁可少留几篇高置信度的，也不要把边缘的都算上。标注集是尺子，尺子本身得准。

**编号在每节内连续，纳入与排除共用一套编号**，回复时直接引用编号。

---

## 一、多用户协作任务卸载与资源分配（已完成复核）

**问题**：多用户协作任务卸载与资源分配

复核结果已应用：移除 6 条判定有误的、移除 3 条无法判断的、新增 3 条，
标注集由 22 条变为 16 条。此节保留供追溯。

### 我判定为「该纳入」（编号 1–22）

1 | 纳入 | 2020 | Collaborative Task Offloading for Overloaded Mobile Edge Computing in Small-Cell Networks
2 | 纳入 | 2023 | Reverse Auction-Based Computation Offloading and Resource Allocation in Mobile Cloud-Edge Computing
3 | 纳入 | 2023 | Joint Optimization of Computing Offloading and Service Caching in Edge Computing-Based Smart Grid
4 | 纳入 | 2020 | A Cyclic Game for Service-Oriented Resource Allocation in Edge Computing
5 | 纳入 | 2025 | A Nash Bargaining Cooperative Game Policy in Mobile Edge Computing
6 | 纳入 | 2017 | Partial Offloading for Latency Minimization in Mobile-Edge Computing
7 | 纳入 | 2022 | Joint Offloading and Resource Allocation With Partial Information for Multi-User Edge Computing
8 | 纳入 | 2021 | D2D-Assisted Multi-User Cooperative Partial Offloading, Transmission Scheduling and Computation Allocating for MEC
9 | 纳入 | 2023 | Task Co-Offloading for D2D-Assisted Mobile Edge Computing in Industrial Internet of Things
10 | 纳入 | 2025 | Incentive-Driven Task Offloading and Collaborative Computing in Device-Assisted MEC Networks
11 | 纳入 | 2023 | Incentive-Based Distributed Resource Allocation for Task Offloading and Collaborative Computing in MEC-Enabled Networks
12 | 纳入 | 2024 | MEC Network Slicing: Stackelberg-Game-Based Slice Pricing and Resource Allocation With QoS Guarantee
13 | 纳入 | 2024 | A Repeated Auction Model for Load-Aware Dynamic Resource Allocation in Multi-Access Edge Computing
14 | 纳入 | 2022 | Signaling-Based Incentive Mechanism for D2D Computation Offloading
15 | 纳入 | 2022 | Incentive-Driven Task Allocation for Collaborative Edge Computing in Industrial Internet of Things
16 | 纳入 | 2021 | Profit-Maximized Collaborative Computation Offloading and Resource Allocation in Distributed Cloud and Edge Computing Systems
17 | 纳入 | 2026 | Privacy-Protected Joint Service Placement and Task Offloading for Knowledge-Defined Cloud-Edge Networking
18 | 纳入 | 2025 | Quality of Experience and Reliability-Aware Task Offloading and Scheduling for Multi-User Mobile-Edge Computing Systems
19 | 纳入 | 2024 | Hybrid Deep Reinforcement Learning-Based Task Offloading for D2D-Assisted Cloud-Edge-Device Collaborative Networks
20 | 纳入 | 2023 | Multi-Agent DRL for Joint Completion Delay and Energy Consumption With Queuing Theory in MEC-Based IIoT
21 | 纳入 | 2024 | SAC-PP: Jointly Optimizing Privacy Protection and Computation Offloading for Mobile Edge Computing
22 | 纳入 | 2025 | Explainable Multiagent Deep Reinforcement Learning for Joint Task Offloading and Resource Allocation in Distance and Channel-Aware NOMA Vehicular Edge Networks

### 我判定为「不该纳入」（编号 23–42）

23 | 排除 | 2018 | Task Offloading for Mobile Edge Computing in Software Defined Ultra-Dense Network
24 | 排除 | 2017 | A Survey on Mobile Edge Computing: The Communication Perspective
25 | 排除 | 2023 | UAV-Aided Computation Offloading in Mobile-Edge Computing Networks: A Stackelberg Game Approach
26 | 排除 | 2024 | A Truthful Incentive Mechanism for Movement-Aware Task Offloading in Crowdsourced Mobile Edge Computing Systems
27 | 排除 | 2020 | Risk-Aware Data Offloading in Multi-Server Multi-Access Edge Computing Environment
28 | 排除 | 2024 | Location Privacy-Aware Task Offloading in Mobile Edge Computing
29 | 排除 | 2022 | Profit Maximization Incentive Mechanism for Resource Providers in Mobile Edge Computing
30 | 排除 | 2022 | TCDA: Truthful Combinatorial Double Auctions for Mobile Edge Computing in Industrial Internet of Things
31 | 排除 | 2026 | Personalized Location Privacy-Aware Task Offloading: A Dual-Agent DRL Approach
32 | 排除 | 2026 | Task Offloading With Differential Privacy in Multi-Access Edge Computing: An A3C-Based Approach
33 | 排除 | 2025 | Revisiting Location Privacy in MEC-Enabled Computation Offloading
34 | 排除 | 2025 | Energy-Privacy Tradeoff for Task Matching in Edge Computing Power Networks
35 | 排除 | 2025 | A Differential Privacy Based Task Offloading Algorithm for Vehicular Edge Computing
36 | 排除 | 2026 | An Entropy-Based Privacy-Preserving Federated Deep Reinforcement Learning Framework for Task Offloading in Vehicular Edge Computing Networks
37 | 排除 | 2025 | Latency and Reliability-Aware Dynamic Task Offloading and Scheduling for Energy-Harvesting Systems in Mobile Edge Computing
38 | 排除 | 2024 | A Game-Theoretic Approach-Based Task Offloading and Resource Pricing Method for Idle Vehicle Devices Assisted VEC
39 | 排除 | 2023 | Computation Offloading Method Using Stochastic Games for Software-Defined-Network-Based Multiagent Mobile Edge Computing
40 | 排除 | 2024 | Privacy-Preserving Offloading Scheme in Multi-Access Mobile Edge Computing Based on MADRL
41 | 排除 | 2024 | Combining Lyapunov Optimization With Actor--Critic Networks for Privacy-Aware IIoT Computation Offloading
42 | 排除 | 2022 | Physics-informed neural networks for non-Newtonian fluid thermo-mechanical problems: An application to rubber calendering process

---

## 二、动态环境下的视觉SLAM与语义建图（待复核）

**问题**：动态环境下的视觉SLAM与语义建图研究进展

我的纳入依据：标题涉及视觉 / 语义 / 动态场景 / 回环 / RGB-D / 单目。
我的排除依据：同属 SLAM 但走激光、水下、嵌入式硬件等其他路线。

### 我判定为「该纳入」（编号 1–15）

1 | 纳入 | 2026 | A Robust and Efficient Visual-Inertial SLAM Using Hybrid Point-Line Features
2 | 纳入 | 2021 | RS-SLAM: A Robust Semantic SLAM in Dynamic Environments Based on RGB-D Sensor
3 | 纳入 | 2025 | DOG-SLAM: Enhancing Dynamic Visual SLAM Precision Through GMM-Based Dynamic Object Removal and ORB-Boost
4 | 纳入 | 2026 | HPGS-SLAM: Hybrid Point-Guided Dense Visual SLAM With Online Mapping via Gaussian Splatting
5 | 纳入 | 2026 | SDT-SLAM: A Short-Term Dynamic Tracking SLAM Algorithm for Dynamic Scenes Based on RGB-D Sensors
6 | 纳入 | 2026 | WaterSplat-SLAM: Photorealistic Monocular SLAM in Underwater Environment
7 | 纳入 | 2025 | RGBDS-SLAM: A RGB-D Semantic Dense SLAM Based on 3D Multi Level Pyramid Gaussian Splatting
8 | 纳入 | 2021 | RDMO-SLAM: Real-Time Visual SLAM for Dynamic Environments Using Semantic Label Prediction With Optical Flow
9 | 纳入 | 2025 | Depth Completion With Multiple Balanced Bases and Confidence for Dense Monocular SLAM
10 | 纳入 | 2024 | ObVi-SLAM: Long-Term Object-Visual SLAM
11 | 纳入 | 2025 | DMN-SLAM: Multi-MLPs Neural Implicit Representation SLAM for Dynamic Environments
12 | 纳入 | 2024 | PIPO-SLAM: Lightweight Visual-Inertial SLAM With Preintegration Merging Theory and Pose-Only Descriptions of Multiple View Geometry
13 | 纳入 | 2026 | IMGS-SLAM: Monocular Gaussian Splatting SLAM for Indoor Reconstruction
14 | 纳入 | 2025 | DFusion-SLAM: A Lightweight Semantic Fusion Framework for Robust Visual SLAM in Dynamic Environments
15 | 纳入 | 2024 | DynaQuadric: Dynamic Quadric SLAM for Quadric Initialization, Mapping, and Tracking

### 我判定为「不该纳入」（编号 16–50）

16 | 排除 | 2019 | HOOFR SLAM System: An Embedded Vision SLAM Algorithm and Its Hardware-Software Mapping-Based Intelligent Vehicles Applications
17 | 排除 | 2023 | Fast and Versatile Feature-Based LiDAR Odometry via Efficient Local Quadratic Surface Approximation
18 | 排除 | 2025 | PttAcc: Pipeline-Based Taylor Expansion Fitting Arctangent Angle Hardware Accelerator Design for Descriptor Duty in ORB-SLAM System
19 | 排除 | 2024 | $D^{2}$SLAM: Decentralized and Distributed Collaborative Visual-Inertial SLAM System for Aerial Swarm
20 | 排除 | 2026 | RP-SLAM: Real-Time Photorealistic SLAM With Efficient 3D Gaussian Splatting
21 | 排除 | 2026 | TGS-SLAM: Tri-Plane Gaussian Splatting for Semantic SLAM
22 | 排除 | 2020 | VPS-SLAM: Visual Planar Semantic SLAM for Aerial Robotic Systems
23 | 排除 | 2024 | Open-Structure: Structural Benchmark Dataset for SLAM Algorithms
24 | 排除 | 2020 | Structure-SLAM: Low-Drift Monocular SLAM in Indoor Environments
25 | 排除 | 2023 | Contour-SLAM: A Robust Object-Level SLAM Based on Contour Alignment
26 | 排除 | 2025 | Fast Inertial-Only SLAM: A Fast Pedestrian SLAM Method for Structured Buildings Based on Foot-Mounted IMU
27 | 排除 | 2025 | A Multi-AUV Collaborative Mapping System With Bathymetric Cooperative Active SLAM Algorithm
28 | 排除 | 2021 | OV$^{2}$SLAM: A Fully Online and Versatile Visual SLAM for Real-Time Applications
29 | 排除 | 2024 | EGLT-SLAM: Real-Time Visual-Inertial SLAM Based on Entropy-Guided Line Tracking
30 | 排除 | 2024 | Finite-Plane Simultaneous Localization and Mapping (FP-SLAM): A New RGB-D SLAM Exploiting Interfeature Relationship
31 | 排除 | 2025 | R4-SLAM: Toward Real-Time, Robust, and Resource-Restricted Visual SLAM in Dynamic Environments
32 | 排除 | 2022 | SO-SLAM: Semantic Object SLAM With Scale Proportional and Symmetrical Texture Constraints
33 | 排除 | 2015 | COP-SLAM: Closed-Form Online Pose-Chain Optimization for Visual SLAM
34 | 排除 | 2025 | DDN-SLAM: Real Time Dense Dynamic Neural Implicit SLAM
35 | 排除 | 2015 | DV-SLAM (Dual-Sensor-Based Vector-Field SLAM) and Observability Analysis
36 | 排除 | 2024 | BASL-AD SLAM: A Robust Deep-Learning Feature-Based Visual SLAM System With Adaptive Motion Model
37 | 排除 | 2024 | Hilti SLAM Challenge 2023: Benchmarking Single + Multi-Session SLAM Across Sensor Constellations in Construction
38 | 排除 | 2025 | CoVOR-SLAM: Cooperative SLAM Using Visual Odometry and Ranges for Multi-Robot Systems
39 | 排除 | 2025 | GRAND-SLAM: Local Optimization for Globally Consistent Large-Scale Multi-Agent Gaussian SLAM
40 | 排除 | 2020 | DeepFactors: Real-Time Probabilistic Dense Monocular SLAM
41 | 排除 | 2015 | ORB-SLAM: A Versatile and Accurate Monocular SLAM System
42 | 排除 | 2022 | UV-SLAM: Unconstrained Line-Based SLAM Using Vanishing Points for Structural Mapping
43 | 排除 | 2024 | SBC-SLAM: Semantic Bioinspired Collaborative SLAM for Large-Scale Environment Perception of Heterogeneous Systems
44 | 排除 | 2025 | LoC-WiFi-SLAM: Low-Complexity of WiFi-Enhanced SLAM
45 | 排除 | 2024 | TextSLAM: Visual SLAM With Semantic Planar Text Features
46 | 排除 | 2021 | RDS-SLAM: Real-Time Dynamic SLAM Using Semantic Segmentation Methods
47 | 排除 | 2017 | Visual-Inertial Monocular SLAM With Map Reuse
48 | 排除 | 2025 | NeuV-SLAM: Fast Neural Multiresolution Voxel Optimization for RGBD Dense SLAM
49 | 排除 | 2023 | UWB Radar SLAM: An Anchorless Approach in Vision Denied Indoor Environments
50 | 排除 | 2008 | Large-Scale SLAM Building Conditionally Independent Local Maps: Application to Monocular Vision
