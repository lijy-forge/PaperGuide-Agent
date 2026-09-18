# PaperGuide 评测

```bash
python -m evals.paperguide --tier demo        # 无需 Key、不联网、结果确定，约 150ms/用例
python -m evals.paperguide --tier retrieval   # 调用真实检索源
python -m evals.paperguide --tier demo --update-baseline   # 更新已提交的基线
```

不带 `--baseline` 时会自动和 `baselines/<tier>.json` 对比，报告里显示指标变化。

## 两个档次

**demo** 用合成语料跑完整流水线。无凭据、无网络、确定性，可以每次改动都跑。它**测不了检索质量**——假检索器返回的就是语料本身，召回率恒为 1。

**retrieval** 调真实的 arXiv、OpenAlex 和 Semantic Scholar，测召回率。用例直接写出英文查询而不是让规划器生成，因为**检索和查询规划失败的原因不同**，一个数字盖住两者就说不清是哪一环动了。

## 现有用例

| 用例 | 档次 | 标注 | 说明 |
| --- | --- | ---: | --- |
| `covered-slam` | demo | — | 问题在语料范围内，不应有范围警告 |
| `partial-yolo` | demo | — | 部分覆盖，应指名缺失的概念 |
| `offtopic-yield` | demo | — | 完全离题，应声明不回答 |
| `full-corpus` | demo | — | 满语料 + 证据覆盖率门槛 |
| `mec-collaborative-offloading` | retrieval | 22 | 通信 |
| `visual-slam-dynamic-semantic` | retrieval | 15 | 机器人 |
| `propellant-yield-stress` | retrieval | 9 | 材料 |

三个检索用例横跨三个学科是有意的：arXiv 对计算机覆盖好、对材料覆盖差，**单一领域的数字会把这个差异藏起来**。

## 标注

标注用**标题**写，由 `annotate resolve` 去真实 API 查回标识符；已有 DOI 的 BibTeX 可以直接填进 `ground_truth`。

**不要手敲标识符。** 敲错的话，系统明明检到了正确论文也会被判成漏检，而且这个错误查不出来——比没有标注更糟。

```bash
python -m evals.paperguide.annotate pool "你的问题" --limit 20      # 看现在能检回什么
python -m evals.paperguide.annotate resolve <用例文件> --apply      # 标题 -> 标识符
python -m evals.paperguide.annotate verify <用例文件>               # 检查标识符仍然有效
```

三个源都按 IP 限流。密集标注时用 `--pause` 放慢；被限流会显示为 `LIMIT` 而不是 `MISS`，两者含义完全不同。

## 阈值与基线

阈值**从实测来，不预设目标**：跑出数字后设成略低于它的值，用来拦住退步。

基线提交在 `baselines/` 而不是 `--out` 指向的目录——后者每次运行都会覆盖，而且被 gitignore，那样"和上次比"就只能在一台机器上成立。含跳过用例的运行不能存为基线：跳过意味着什么都没测到，存下来会让下次对比把源故障读成质量变化。

## 待办

**跑三个检索用例的首次基线。** 标注已备齐，等 API 限流冷却。阈值目前是 0.0，因为还没测过。

**建一档决策评测。** 现有两档量的是"检索得好不好"，量不到"判断得对不对"。项目里有两个真实的决策点：

- `MetadataRelevanceGate` 与 `EvidenceAwareFinalRelevanceService` 决定一篇论文是否选入核心文献。**过度纳入**会把不相关的论文写进综述。
- `EvidenceSufficiencyAssessment` 决定出完整综述还是降级为证据有限综述。**该降级不降级**，就是拿不足的证据写出看起来完整的报告。

demo 档那三个范围判定用例已经是这种形态（人工判定的期望行为 + 系统实际行为 + 是否一致），但 3 条算不出有意义的一致率。要做起来**需要标注负样本**——不该选入的论文、不该出完整综述的证据状态——而正样本标注只完成了一半。
