# PaperPilot real demo checklist

This checklist distinguishes manual real-runtime evidence from automated Fake tests. As of 2026-08-05, the repository environment had no configured LLM credential and its validation interpreter lacked PyMuPDF, so the real items below remain unchecked.

## Scenario A — minimum successful chain

- Question: `What methods combine YOLO with visual SLAM?`
- Sources: arXiv only
- Maximum papers: 1
- Export: Markdown

- [ ] Provider initialized using a local environment credential
- [ ] Paper retrieved and normalized
- [ ] PDF downloaded, validated, and parsed
- [ ] Structured reading completed
- [ ] Evidence mapped and verified
- [ ] Report verified and exported
- [ ] `smoke-result.json` contains only safe diagnostics

## Scenario B — interview demo topic

- Question: `分析 YOLO 与 SLAM 融合在语义建图中的研究方法和实施路线`
- Sources: arXiv and Semantic Scholar
- Maximum papers: 3
- Export: Markdown

- [ ] Multi-source retrieval succeeds or reports an isolated source failure
- [ ] Duplicate papers are merged
- [ ] At least one verified paper reaches the quality gate
- [ ] Final report contains working evidence citations
- [ ] Artifact downloads from the dashboard

Run manually only after Scenario A passes:

```powershell
poetry run python -m paperpilot.smoke `
  --question "分析 YOLO 与 SLAM 融合在语义建图中的研究方法和实施路线" `
  --source arxiv --source semantic_scholar `
  --max-papers 3 --format markdown
```

## Scenario C — safe failure diagnosis

Run exactly one controlled failure, such as an invalid provider name, an unwritable output directory, or a stopped TaskHost.

- [ ] Terminal/API response is clear and non-sensitive
- [ ] No credential, absolute local path, prompt, question text, or PDF content appears in diagnostics
- [ ] Failed stage is not marked successful
- [ ] Downstream stages are marked skipped

## Host, API, and dashboard walkthrough

- [ ] Runtime readiness is true while TaskHost is healthy
- [ ] New research submission succeeds
- [ ] UI navigates to Task Detail automatically
- [ ] Status changes from queued to running
- [ ] Event Timeline updates
- [ ] Browser refresh restores the task
- [ ] A recent task can be reopened
- [ ] Task reaches completed or an explicit quality-gate terminal state
- [ ] Artifact download succeeds
- [ ] Stopping TaskHost makes readiness unavailable
- [ ] API errors do not expose internal paths
- [ ] Browser console does not contain the question body

Record the date, provider/model names (never credentials), source availability, artifact checksum, and any incident separately after execution. Do not commit a real result until it has been reviewed for sensitive or copyrighted content.
