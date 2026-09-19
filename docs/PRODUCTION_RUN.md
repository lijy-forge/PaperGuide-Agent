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
export PAPERGUIDE_MODEL_PRICE_USD_PER_MTOK="3.00,15.00"
```

填错格式会直接报错而不是忽略——被忽略的话每次运行都会显示成免费，那比没有数字更糟。

### 先解决代理

PDF 链接常常是 `http://` 而不是 `https://`，会落进 `HTTP_PROXY` 的作用范围。
本机配了代理时下载会报 502，看上去像论文源挂了。

```bash
unset HTTP_PROXY http_proxy
```

## 跑

```bash
PAPERGUIDE_RUN_REAL_E2E=1 python3 -m paperguide.runtime research --question "你的问题"
```

`PAPERGUIDE_RUN_REAL_E2E` 是显式开关：没有它，任何真实网络或模型调用都不会发生。
这样"不小心花了钱"不可能发生。

## 会遇到的两件事

**下载不到全部论文。** 实测 15 条结果里 11 条有 PDF 链接，试下载 8 条成功 3 条：
arXiv 和开放获取的 IEEE 能下，ScienceDirect 和部分机构库返回 403。这是版权限制，
不是工具问题。付费墙后的论文用手工上传功能自己提供 PDF。

**token 数是本地估的。** 上游的补全函数只返回文本，提供方报的用量在进程里拿不到，
所以是用 tiktoken 在本地数的。对 OpenAI 的模型误差在几个百分点；换成 Claude 用的是
另一套分词器，这个数字只能当量级参考，不能当账单。

## 别把这两件事说成一件

到 2026-09-19 为止，这个仓库里**没有证据表明完整链路在真实数据上跑通过**：运行时库里
的任务全是 demo 模式，CI 也没有引用 `PAPERGUIDE_RUN_REAL_E2E`。

已经实测过的是检索和下载这一段。完整链路的覆盖来自 demo 模式的确定性测试。
跑通一次真实调研之前，这两句话要分开说。
