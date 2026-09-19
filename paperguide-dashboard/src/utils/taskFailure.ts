/** What a failure code means, and what the reader can do about it.
 *
 * The API deliberately returns a code rather than the server's error text, so
 * this is where a code becomes an explanation. Without it a run that failed
 * for a reason the reader controls — asking for years no paper was published
 * in — looks exactly like a crash, and the only honest next step is "retry",
 * which would fail again in precisely the same way.
 */
export interface FailureExplanation {
  title: string;
  detail: string;
  /** Whether retrying unchanged could plausibly succeed. */
  retryWorthwhile: boolean;
}

const EXPLANATIONS: Record<string, FailureExplanation> = {
  NO_PAPERS_IN_TIME_RANGE: {
    title: "指定年份范围内没有文献",
    detail:
      "检索到了文献，但没有一篇的发表年份落在问题里指定的范围内，因此没有任何证据可以引用。" +
      "放宽或去掉年份限定后重新提交。注意离线演示模式使用固定语料，年份覆盖有限。",
    retryWorthwhile: false
  },
  NO_EVIDENCE_FOR_QUESTION: {
    title: "没有找到可引用的文献",
    detail:
      "检索没有返回可用的文献，报告里将没有任何参考文献，因此没有导出。" +
      "可能是检索源暂时不可用，也可能是问题过窄；换个说法或稍后重试。",
    retryWorthwhile: true
  },
  REPORT_QUALITY_REJECTED: {
    title: "报告未通过质量校验",
    detail:
      "报告生成了，但没有通过导出前的校验（例如引用编号对不上参考文献）。" +
      "为避免给出不可追溯的结论，系统选择不导出。",
    retryWorthwhile: true
  },
  TASK_DEAD_LETTER: {
    title: "多次执行失败后已放弃",
    detail:
      "执行该任务的进程反复中断，达到重试上限后任务被移入死信队列，不再自动重试。",
    retryWorthwhile: false
  },
  TASK_FAILED: {
    title: "任务执行失败",
    detail:
      "执行过程中出现未预期的错误。详细原因不会返回给浏览器，需要查看服务端日志。",
    retryWorthwhile: true
  }
};

export function explainFailure(code: string | null): FailureExplanation | null {
  if (!code) return null;
  // An unknown code still deserves a panel: saying nothing would leave the
  // reader with a bare status and no indication that a reason exists.
  return EXPLANATIONS[code] ?? EXPLANATIONS.TASK_FAILED;
}
