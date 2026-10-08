# 跑一次真实调研

Demo 模式把检索器和模型两端都换成了假的，所以它证明不了检索质量，也证明不了
报告是模型真写出来的。这份说明是跑真实链路要做的事。

## 先弄清楚 Key 管什么

Key 只用在调模型的地方。检索和下载不经过模型，没有 Key 也能跑。

| 环节 | 要 Key |
| --- | --- |
| 把问题拆成检索词 | 是 |
| arXiv / OpenAlex / Semantic Scholar 检索 | 否 |
| 下载 PDF | 否 |
| 解析 PDF 文本 | 否 |
| 读论文、抽取论断与证据 | 是 |
| 核验证据是否支持论断 | 是 |
| 写综述 | 是 |

## 配置

```bash
pip install langchain_anthropic          # 用 OpenAI 则不需要

export ANTHROPIC_API_KEY=...             # 自己填，不要写进仓库
export PAPERGUIDE_MODE=production
export PAPERGUIDE_LLM_PROVIDER=anthropic
export PAPERGUIDE_MODEL_NAME=claude-sonnet-5
export PAPERGUIDE_MAX_PAPERS=3           # 第一次先少跑几篇
export PAPERGUIDE_CONTACT_EMAIL=you@example.com   # OpenAlex 礼貌池，可选
```

### 成本要自己填价格

内置价格表只覆盖写它时的那几个 OpenAI 模型，别的模型成本会报「未知」而不是 0。
价格从提供方的定价页抄，按**每百万 token 的美元数**填，输入在前：

```bash
# Claude Sonnet 5，2026-09-19 从 claude.com/pricing 核实
export PAPERGUIDE_MODEL_PRICE_USD_PER_MTOK="2.00,10.00"
```

换模型就换这两个数字。Sonnet 4.6 和 4.5 是 3.00/15.00，Opus 5 是 5.00/25.00，
Haiku 4.5 是 1.00/5.00。

填错格式会直接报错而不是忽略——被忽略的话每次运行都会显示成免费，那比没有数字更糟。

### 先解决代理

**这一节此前写的 `NO_PROXY='*'` 是错的，照做会让运行必然失败。** 它只考虑了检索，
没考虑模型调用，而这两半需要相反的设置。

检索源和 Anthropic API 对代理的要求正好相反（2026-09-19 实测，检索源两轮一致）：

| 目标 | 直连 | 走代理 |
| --- | --- | --- |
| Anthropic API | **403 Request not allowed** | **200** |
| OpenAlex | **通** | 429 |
| Crossref | 通 | 通 |
| arXiv | 406 | 406 |
| Semantic Scholar | 429 | 429 |

API 那个 403 是地区封锁，不是 Key 的问题——同一个 Key 走代理能正常列出模型。而代理的
出口 IP 是共享的、早被用超，所以 OpenAlex 直连正常、走代理反被限流。

`NO_PROXY='*'` 把所有流量都排除出代理，于是检索能跑、模型调用全部 403，整轮运行拿不到
任何结果。正确做法是**代理照开，只把被限流的检索源排除出去**：

```bash
export HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897
export NO_PROXY='api.openalex.org,api.crossref.org,arxiv.org,export.arxiv.org,api.semanticscholar.org'
```

端口换成你自己的。没有代理、且所在地区能直连 Anthropic 的话，`NO_PROXY='*'` 才是对的。

PDF 下载走代理是可行的：实测 10 篇选中的论文下载成功 3 篇，失败的是出版商 403 和
doi.org 返回 HTML 落地页，与代理无关。

## 跑

代理按上一节设好，然后：

```bash
PAPERGUIDE_RUN_REAL_E2E=1 python3 -m paperguide.runtime research "你的问题"
```

`PAPERGUIDE_RUN_REAL_E2E` 是显式开关：没有它，任何真实网络或模型调用都不会发生。
这样"不小心花了钱"不可能发生。

## 会遇到的几件事

**下载不到全部论文。** 实测 15 条结果里 11 条有 PDF 链接，试下载 8 条成功 3 条：
arXiv 和开放获取的 IEEE 能下，ScienceDirect 和部分机构库返回 403。这是版权限制，
不是工具问题。付费墙后的论文用手工上传功能自己提供 PDF。

**Crossref 从不给 PDF。** 它是 DOI 注册机构，只登记元数据。所以在只有 Crossref
能用的时段，检索得到论文、拿不到全文，报告会退化成只有标题摘要的版本。

**token 数是本地估的。** 上游的补全函数只返回文本，提供方报的用量在进程里拿不到，
所以是用 tiktoken 在本地数的。对 OpenAI 的模型误差在几个百分点；换成 Claude 用的是
另一套分词器，这个数字只能当量级参考，不能当账单。

## 目前真实数据跑到哪一步

2026-09-19 实测，`claude-sonnet-5` + OpenAlex/Crossref（arXiv 和 Semantic Scholar 当时
在限流）：

| 阶段 | 结果 |
| --- | --- |
| 检索 | 5 条查询，50 条候选 |
| 元数据筛选 | 选出 10 篇 |
| 下载解析 | 下到 3 篇，全部解析成功 |
| 分析与核验 | 2 篇，**10 条已核验证据** |
| 图的质量门 | 通过（`verification quality thresholds were met`） |
| 生成报告 | **失败，无产物** |

最后一步失败的原因已经定位：报告只引用 `final_classification is CORE` 的论文
（`citations.py:475` → `survey.py:361`），而那 2 篇是 ADJACENT，于是 10 条证据一条都
用不上，`evidence_link_keys` 为空。

之后的修改让报告改为引用"有已核验证据"的论文，CORE 只决定排序。这一点目前只有单元测试
支撑，**还没有在真实数据上重跑过**：那轮调试把 OpenAlex 跑成了持续 429。上表是修改之前
的结果，重跑之前不能写成"已跑通"。

CI 仍然没有引用 `PAPERGUIDE_RUN_REAL_E2E`，完整链路的自动化覆盖依旧只来自 demo 模式的
确定性测试。"某一段实测过"和"链路被自动验证"仍然是两句话。
