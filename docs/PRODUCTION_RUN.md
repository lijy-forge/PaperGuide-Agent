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

**`unset HTTP_PROXY` 是不够的，而且会让情况更糟。** 环境变量一清空，urllib 就去读
macOS 的系统代理设置，那里往往配着 https 代理——于是本来直连的 API 请求全部改走代理。
正确做法是显式声明不走代理：

```bash
export NO_PROXY='*' no_proxy='*'
```

这件事有实测支撑（2026-09-19，两轮一致）：

| 源 | 直连 | 走代理 |
| --- | --- | --- |
| Crossref | 通 | 通 |
| OpenAlex | **通** | **429** |
| arXiv | 406 | 406 |
| Semantic Scholar | 429 | 429 |

直连能用两个源，走代理只剩一个。代理的出口 IP 是共享的，早已被别人用超，所以
OpenAlex 直连正常、走代理反而被限流。

PDF 下载是另一回事：链接常常是 `http://` 而不是 `https://`，正好落进 `HTTP_PROXY`
的作用范围，会报 502。`NO_PROXY='*'` 一并解决。

## 跑

```bash
export NO_PROXY='*' no_proxy='*'
PAPERGUIDE_RUN_REAL_E2E=1 python3 -m paperguide.runtime research --question "你的问题"
```

`PAPERGUIDE_RUN_REAL_E2E` 是显式开关：没有它，任何真实网络或模型调用都不会发生。
这样"不小心花了钱"不可能发生。

## 会遇到的两件事

**下载不到全部论文。** 实测 15 条结果里 11 条有 PDF 链接，试下载 8 条成功 3 条：
arXiv 和开放获取的 IEEE 能下，ScienceDirect 和部分机构库返回 403。这是版权限制，
不是工具问题。付费墙后的论文用手工上传功能自己提供 PDF。

**Crossref 从不给 PDF。** 它是 DOI 注册机构，只登记元数据。所以在只有 Crossref
能用的时段，检索得到论文、拿不到全文，报告会退化成只有标题摘要的版本。

**token 数是本地估的。** 上游的补全函数只返回文本，提供方报的用量在进程里拿不到，
所以是用 tiktoken 在本地数的。对 OpenAI 的模型误差在几个百分点；换成 Claude 用的是
另一套分词器，这个数字只能当量级参考，不能当账单。

## 别把这两件事说成一件

到 2026-09-19 为止，这个仓库里**没有证据表明完整链路在真实数据上跑通过**：运行时库里
的任务全是 demo 模式，CI 也没有引用 `PAPERGUIDE_RUN_REAL_E2E`。

已经实测过的是检索和下载这一段。完整链路的覆盖来自 demo 模式的确定性测试。
跑通一次真实调研之前，这两句话要分开说。
