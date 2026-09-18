# 推进剂用例复核清单（已完成）

**文件**：`evals/paperguide/cases/retrieval/propellant-yield-stress.yaml`
**问题**：复合推进剂浆料屈服应力预测研究进展

> **复核结论**：9 条标题到 DOI 的解析全部人工确认无误，提取的标题为准。
> 含相似度 0.74 和 0.88 的两条在内，均确认指向同一篇论文。此文档保留供追溯。

## 这次要核的和前两个不一样

前两个用例核的是「这篇该不该纳入」。这个用例的标题你已经审过一轮了（删掉了醪液黏度、
聚合物信息学、分子性质预测三条），所以要核的是另一件事：

> **从 PDF 提取的标题，解析到的 DOI 是不是同一篇论文？**

标题是我用字号启发式从 PDF 首页提取的，**这批 PDF 里 20 篇曾错 5 篇**（抓成期刊名或
作者名）。解析用的是标题相似度 ≥0.72，所以一个截断或提错的标题**可能匹配到另一篇论文**，
而这种错误在召回率里查不出来——系统检到了正确论文，标注却指向别的论文，永远判为漏检。

相似度低于 0.90 的已标出，那几条最可能出问题。

## 逐条核对

1 | 相似度 1.00
  我的标题（从 PDF 提取）: Yield stress and maximum packing fraction of concentrated suspensions
  解析到的论文（API 返回）: Yield stress and maximum packing fraction of concentrated suspensions
  doi:10.1007/bf00712315
2 | 相似度 0.99
  我的标题（从 PDF 提取）: The rheology of concentrated suspensions of arbitrarily shaped particles
  解析到的论文（API 返回）: The rheology of concentrated suspensions of arbitrarily-shaped particles
  doi:10.1016/j.jcis.2010.02.033
3 | 相似度 0.74  ⚠ 相似度偏低
  我的标题（从 PDF 提取）: Rheology and applications of highly filled polymers
  解析到的论文（API 返回）: Rheology and applications of highly filled polymers: A review of current understanding
  doi:10.1016/j.progpolymsci.2016.12.007
4 | 相似度 0.88  ⚠ 相似度偏低
  我的标题（从 PDF 提取）: Rapid Temperature-Dependent Rheological Measurements of Non-Newtonian Solutions Using a Machine-Learning Aided Microfluidic Rheometer
  解析到的论文（API 返回）: Rapid Temperature-Dependent Rheological Measurements of Non-Newtonian Solutions
  doi:10.1021/acs.analchem.1c05208
5 | 相似度 0.99
  我的标题（从 PDF 提取）: integrated experimental numerical analysis of htpb propellant casting optimization and droplet dynamics
  解析到的论文（API 返回）: Integrated Experimental–Numerical Analysis of HTPB Propellant Casting Optimization
  doi:10.1021/acsomega.5c03072
6 | 相似度 0.99
  我的标题（从 PDF 提取）: Discontinuous shear thickening without inertia in dense non Brownian suspensions
  解析到的论文（API 返回）: Discontinuous Shear Thickening without Inertia in Dense Non-Brownian Suspensions
  doi:10.1103/physrevlett.112.098302
7 | 相似度 1.00
  我的标题（从 PDF 提取）: Yield-stress transition in suspensions of deformable droplets
  解析到的论文（API 返回）: Yield-stress transition in suspensions of deformable droplets
  doi:10.1126/sciadv.adf8106
8 | 相似度 1.00
  我的标题（从 PDF 提取）: Research on Time-Dimension Expansion of HBP Model Based on Hydroxyl-Terminated Polybutadiene (HTPB) Propellant Slurry
  解析到的论文（API 返回）: Research on Time-Dimension Expansion of HBP Model Based on Hydroxyl-Terminated Polybutadiene Propellant Slurry
  doi:10.3390/polym17121682
9 | 相似度 0.97
  我的标题（从 PDF 提取）: Studies on Measurement of Yield Stress of Propellant Suspensions using Falling Ball and Slump Test
  解析到的论文（API 返回）: Studies on Measurement of Yield Stress of Propellant Suspensions
  doi:10.3933/applrheol-27-45262

## 判断方式

对每一条问：**上下两行是同一篇论文吗？**

- 是 → 保留
- 否 → 告诉我编号，我移除
- 拿不准 → 用 DOI 查一下原文（`https://doi.org/<DOI>`）

特别留意第 3 条（0.74）：我的标题是 `Rheology and applications of highly filled polymers`，
解析到的是 `...: A review of current understanding`。看起来是同一篇的完整标题，但需要确认。

## 另有 3 条未能解析

以下标题在 API 里没找到对应论文，已移入 `unresolved_titles`，不参与召回计算：

- Advances in Fluid Viscosity Measurement Technologies
- Characterizing the non Newtonian viscosity of high solids
- Constitutive Modeling of Rheological Behavior of Cement Paste Based on Material Composition

第一条原文是中文《流体粘度测量技术研究进展》，我提取时给了个英文标题——那是我编的，
不是论文的真实标题，所以查不到是正常的。如果你要把它纳入标注集，需要提供真实标题或 DOI。
