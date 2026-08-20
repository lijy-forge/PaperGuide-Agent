import { Alert, Spin, Table, Typography } from "antd";
import { Fragment, useEffect, useState, type ReactNode } from "react";

function readBlobText(blob: Blob): Promise<string> {
  if (typeof blob.text === "function") return blob.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsText(blob);
  });
}

function isTableDivider(line: string): boolean {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function tableCells(line: string): string[] {
  return line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
}

/** Minimal Markdown renderer that emits escaped React text nodes and never raw HTML. */
export function renderSafeMarkdown(markdown: string): ReactNode[] {
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  const output: ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (line.startsWith("```")) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) code.push(lines[index++]);
      if (index < lines.length) index += 1;
      output.push(<pre key={`code-${index}`}><code>{code.join("\n")}</code></pre>);
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      output.push(<Typography.Title level={Math.min(level, 5) as 1 | 2 | 3 | 4 | 5} key={`heading-${index}`}>{heading[2]}</Typography.Title>);
      index += 1;
      continue;
    }
    if (line.includes("|") && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      const headers = tableCells(line);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) rows.push(tableCells(lines[index++]));
      output.push(<Table key={`table-${index}`} size="small" pagination={false} dataSource={rows.map((row, rowIndex) => ({ key: rowIndex, row }))} columns={headers.map((header, columnIndex) => ({ title: header, key: String(columnIndex), render: (_value: unknown, record: { row: string[] }) => record.row[columnIndex] ?? "" }))} />);
      continue;
    }
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) items.push(lines[index++].replace(/^\s*[-*+]\s+/, ""));
      output.push(<ul key={`list-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</ul>);
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) items.push(lines[index++].replace(/^\s*\d+[.)]\s+/, ""));
      output.push(<ol key={`ordered-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</ol>);
      continue;
    }
    if (/^\s*>\s?/.test(line)) {
      output.push(<blockquote key={`quote-${index}`}>{line.replace(/^\s*>\s?/, "")}</blockquote>);
      index += 1;
      continue;
    }
    if (line.trim()) output.push(<Typography.Paragraph key={`paragraph-${index}`}>{line}</Typography.Paragraph>);
    else output.push(<Fragment key={`space-${index}`} />);
    index += 1;
  }
  return output;
}

export function MarkdownViewer({ blob }: { blob: Blob }) {
  const [markdown, setMarkdown] = useState<string>();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    setMarkdown(undefined);
    setFailed(false);
    void readBlobText(blob).then((text) => { if (active) setMarkdown(text); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [blob]);
  if (failed) return <Alert role="alert" type="error" message="无法渲染报告。" />;
  if (markdown === undefined) return <Spin tip="正在加载报告…"><div className="artifact-viewer-loading" /></Spin>;
  try {
    return <article className="markdown-report">{renderSafeMarkdown(markdown)}</article>;
  } catch {
    return <Alert role="alert" type="error" message="无法渲染报告。" />;
  }
}
