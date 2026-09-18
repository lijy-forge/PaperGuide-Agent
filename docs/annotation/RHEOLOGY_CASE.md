# 第四个检索用例：题目待定

这批来自你 Downloads 里的 41 个 bib 文件，去重后与流变/粘度相关且带 DOI 的共 18 篇。

**它们和现有的 `propellant-yield-stress` 用例不是同一个主题**——那个问的是复合推进剂
浆料的屈服应力，这批讲的是用机器学习和传感器预测/测量流变性质。所以我没有把它们
并进去：标注集掺入相邻主题后，召回率就说不清是检索差还是这篇本来就该排在后面。

## 候选题目

### 选项一：机器学习在流变参数预测中的应用（13 篇）

覆盖最集中的一组，物理信息神经网络、数据驱动建模都在里面。

- 2023 | Predicting viscosity of ionic liquids - water mixtures by bridging UNIFAC modeling with interpretable machine learning
  `doi:10.1016/j.molliq.2023.122095`
- 2025 | Probing rate-dependent liquid shear viscosity using combined machine learning and nonequilibrium molecular dynamics
  `doi:10.1021/acs.jctc.5c00293`
- 2025 | A physics-enforced neural network to predict polymer melt viscosity
  `doi:10.1038/s41524-025-01532-6`
- 2024 | Hybrid data-driven and physics-based modeling for viscosity prediction of ionic liquids
  `doi:10.1016/j.gee.2024.01.007`
- 2025 | Learning rheological parameters of non-Newtonian fluids from velocimetry data
  `doi:10.17863/cam.113320`
- 2025 | Data-driven techniques in rheology: Developments, challenges and perspective
  `doi:10.1016/j.cocis.2024.101873`
- 2024 | Advancing material property prediction using physics-informed machine learning models for viscosity
  `doi:10.1122/1.5500123`
- 2025 | A physics-informed neural network solution for rheological modeling of cement slurries
  `doi:10.3390/fluids10070184`
- 2023 | RheologyNet: A physics-informed neural network solution to evaluate the thixotropic properties of cementitious materials
  `doi:10.1016/j.cemconres.2023.107157`
- 2024 | Advancing material property prediction: using physics-informed machine learning models for viscosity
  `doi:10.1186/s13321-024-00820-5`
- 2022 | Rapid temperature-dependent rheological measurements of non-Newtonian solutions using a machine-learning aided microfluidic rheometer
  `doi:10.1021/acs.analchem.1c05208`
- 2020 | Comparison of individual and integrated inline Raman, near-infrared, and mid-infrared spectroscopic models to predict the viscosity of micellar liquids
  `doi:10.1177/0003702820921008`
- 2023 | Machine learning based microfluidic sensing device for viscosity measurements
  `doi:10.1039/d3sd00099k`

### 选项二：流变性质的在线测量与预测（18 篇）

把传感器测量那部分也并进来，样本更大，但问题的边界更宽、更难判定该不该纳入。

额外包含：

- 2022 | Rheology and structure of lithium-ion battery electrode slurries
  `doi:10.1002/ente.202200545`
- 2022 | Accuracy and precision of resonant piezoelectric {MEMS} viscosity sensors in highly viscous bituminous materials
  `doi:10.1016/j.sna.2022.113903`
- 2021 | Real-time measurement of drilling fluid rheological properties: a review
  `doi:10.3390/en14092479`
- 2024 | Ultrasonic sensor: a fast and non-destructive system to measure the viscosity and density of molecular fluids
  `doi:10.3390/bios14070346`
- 2022 | Characterizing the non-Newtonian viscosity of high-solids drilling-fluid suspensions by flow loop
  `doi:10.1063/5.0098462`

## 怎么定

看你实际关心哪个问题。判断标准还是那句：**你提出这个问题时，哪些论文没检索到算漏了。**

选项一边界清楚，适合做标注集；选项二样本大但边界模糊，标注争议会多。

定了告诉我题目和要纳入的编号，我建用例。也可以两个都建——它们能相互对照，
一个窄问题和一个宽问题在同一批文献上的召回差异本身就是有意义的信息。
