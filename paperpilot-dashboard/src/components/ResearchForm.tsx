import {
  Alert,
  Button,
  Card,
  Divider,
  Form,
  Input,
  InputNumber,
  Radio,
  Select,
  Space,
  Typography,
  Upload
} from "antd";
import { DeleteOutlined, PlusOutlined, UploadOutlined } from "@ant-design/icons";
import type { UploadFile } from "antd";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import {
  createResearch,
  MAX_RESEARCH_QUESTION_LENGTH,
  uploadManualSource
} from "../api/research";
import type {
  ExportFormat,
  ManualPaperSource,
  ManualSourceProvider,
  ResearchRequest
} from "../api/types";
import { addRecentTask, createLocalTitle } from "../utils/recentTasks";

export const MIN_RESEARCH_QUESTION_LENGTH = 10;

interface SubmissionError {
  message: string;
  hostOffline: boolean;
}

interface ManualSourceFormValue {
  source: ManualSourceProvider;
  title: string;
  source_url: string;
  authors_text?: string;
  publication_year?: number;
  abstract?: string;
  doi?: string;
  pdf_file: UploadFile[];
}

interface ResearchFormValues {
  question: string;
  max_papers: number;
  export_format: ExportFormat;
  manual_sources?: ManualSourceFormValue[];
}

export function isValidMaxPapers(value: unknown): boolean {
  return Number.isInteger(value) && Number(value) >= 1 && Number(value) <= 50;
}

export function researchSubmissionError(error: unknown): SubmissionError {
  if (error instanceof ApiError) {
    if (error.code === "INVALID_REQUEST" || error.status === 422) {
      return { message: "请求无效，请检查调研问题和人工文献字段。", hostOffline: false };
    }
    if (error.code === "INVALID_PDF" || error.code === "PDF_TOO_LARGE") {
      return { message: "人工补充 PDF 无效、已加密或超过 50 MB。", hostOffline: false };
    }
    if (error.code === "TASK_HOST_UNAVAILABLE" || error.status === 503) {
      return { message: "任务主机不可用。", hostOffline: true };
    }
    if (error.code === "API_UNAVAILABLE" || error.status === undefined) {
      return { message: "PaperPilot API 不可用。", hostOffline: false };
    }
  }
  return { message: "创建调研任务失败。", hostOffline: false };
}

export function researchSubmissionErrorMessage(error: unknown): string {
  const result = researchSubmissionError(error);
  return result.hostOffline
    ? `${result.message} 请运行：paperpilot server start`
    : result.message;
}

function splitAuthors(value?: string): string[] {
  return (value ?? "")
    .split(/[;,，；\n]/)
    .map((name) => name.trim())
    .filter(Boolean);
}

export function ResearchForm({ onSubmitted }: { onSubmitted: (taskId: string) => void }) {
  const [form] = Form.useForm<ResearchFormValues>();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<SubmissionError>();
  const submitLock = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  async function handleSubmit(values: ResearchFormValues) {
    if (submitLock.current) return;
    submitLock.current = true;
    setSubmitting(true);
    setError(undefined);
    try {
      const manualSources: ManualPaperSource[] = await Promise.all(
        (values.manual_sources ?? []).map(async (item) => {
          const file = item.pdf_file?.[0]?.originFileObj;
          if (!file) throw new Error("manual PDF is required");
          const uploaded = await uploadManualSource(file as File);
          return {
            source: item.source,
            title: item.title.trim(),
            source_url: item.source_url.trim(),
            upload_id: uploaded.upload_id,
            authors: splitAuthors(item.authors_text),
            publication_year: item.publication_year,
            abstract: item.abstract?.trim() || undefined,
            doi: item.doi?.trim() || undefined
          };
        })
      );
      const payload: ResearchRequest = {
        question: values.question.trim(),
        max_papers: values.max_papers,
        export_format: values.export_format,
        manual_sources: manualSources
      };
      const result = await createResearch(payload);
      addRecentTask({
        taskId: result.task_id,
        createdAt: result.created_at,
        localTitle: createLocalTitle(payload.question),
        exportFormat: payload.export_format
      });
      if (mounted.current) onSubmitted(result.task_id);
    } catch (nextError) {
      if (mounted.current) setError(researchSubmissionError(nextError));
    } finally {
      submitLock.current = false;
      if (mounted.current) setSubmitting(false);
    }
  }

  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={{ max_papers: 15, export_format: "markdown", manual_sources: [] }}
      onFinish={(values) => void handleSubmit(values)}
      requiredMark="optional"
    >
      {error && (
        <Alert
          className="form-alert"
          role="alert"
          type="error"
          showIcon
          message={error.message}
          description={error.hostOffline ? <span>请运行：<Typography.Text code>paperpilot server start</Typography.Text></span> : undefined}
          action={<Button onClick={() => form.submit()}>重试</Button>}
        />
      )}

      <Alert
        className="source-mode-alert"
        type="info"
        showIcon
        message="混合文献来源模式"
        description="arXiv 与 Semantic Scholar 自动检索；Google Scholar 与知网用于人工补充，并与自动结果统一去重、解析和证据验证。"
      />

      <Form.Item
        label="调研问题"
        name="question"
        rules={[
          { required: true, whitespace: true, message: "请输入调研问题。" },
          {
            validator: (_, value: string | undefined) => {
              const length = value?.trim().length ?? 0;
              if (length === 0) return Promise.resolve();
              if (length < MIN_RESEARCH_QUESTION_LENGTH) return Promise.reject(new Error(`调研问题至少需要 ${MIN_RESEARCH_QUESTION_LENGTH} 个字符。`));
              if (length > MAX_RESEARCH_QUESTION_LENGTH) return Promise.reject(new Error(`调研问题不能超过 ${MAX_RESEARCH_QUESTION_LENGTH.toLocaleString()} 个字符。`));
              return Promise.resolve();
            }
          }
        ]}
      >
        <Input.TextArea
          rows={7}
          maxLength={MAX_RESEARCH_QUESTION_LENGTH}
          showCount={{ formatter: ({ count, maxLength }) => `${count} / ${maxLength}` }}
          placeholder="例如：分析 2024—2026 年 YOLO 与 SLAM 融合研究进展"
          aria-label="调研问题"
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
              event.preventDefault();
              form.submit();
            }
          }}
        />
      </Form.Item>

      <div className="form-grid">
        <Form.Item
          label="最大论文数量"
          name="max_papers"
          extra="技术综述建议 12—20 篇；人工补充文献也计入分析池。"
          rules={[
            { required: true, message: "请选择最大论文数量。" },
            { validator: (_, value: unknown) => isValidMaxPapers(value) ? Promise.resolve() : Promise.reject(new Error("论文数量必须在 1 到 50 之间。")) }
          ]}
        >
          <InputNumber min={1} max={50} precision={0} aria-label="最大论文数量" />
        </Form.Item>
        <Form.Item label="导出格式" name="export_format" rules={[{ required: true }]}>
          <Radio.Group aria-label="导出格式">
            <Radio.Button value="markdown">Markdown</Radio.Button>
            <Radio.Button value="html">HTML</Radio.Button>
            <Radio.Button value="pdf">PDF</Radio.Button>
          </Radio.Group>
        </Form.Item>
      </div>

      <Divider orientation="left">Google Scholar / 知网人工补充</Divider>
      <Typography.Paragraph className="manual-source-help">
        请先在 Google Scholar 或知网中确认真实文献，合法下载 PDF 后上传。系统不绕过付费墙，也不会要求或保存账号密码。每个条目必须提供出处链接和 PDF，才能提取贡献、局限及页码证据。
      </Typography.Paragraph>

      <Form.List name="manual_sources">
        {(fields, { add, remove }) => (
          <Space direction="vertical" size={14} className="manual-source-list">
            {fields.map(({ key, name, ...restField }, index) => (
              <Card
                key={key}
                size="small"
                className="manual-source-card"
                title={`人工文献 ${index + 1}`}
                extra={<Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(name)}>移除</Button>}
              >
                <div className="form-grid">
                  <Form.Item {...restField} label="来源" name={[name, "source"]} rules={[{ required: true, message: "请选择来源。" }]}>
                    <Select options={[{ value: "google_scholar", label: "Google Scholar" }, { value: "cnki", label: "中国知网（CNKI）" }]} />
                  </Form.Item>
                  <Form.Item {...restField} label="发表年份" name={[name, "publication_year"]}>
                    <InputNumber min={1900} max={2100} precision={0} placeholder="例如 2024" />
                  </Form.Item>
                </div>
                <Form.Item {...restField} label="文献标题" name={[name, "title"]} rules={[{ required: true, whitespace: true, message: "请输入真实文献标题。" }]}>
                  <Input placeholder="请按检索结果中的正式标题填写" />
                </Form.Item>
                <Form.Item {...restField} label="出处链接" name={[name, "source_url"]} rules={[{ required: true, type: "url", message: "请输入有效的 HTTPS 出处链接。" }, { pattern: /^https:\/\//i, message: "出处链接必须使用 HTTPS。" }]}>
                  <Input placeholder="Google Scholar 结果页、出版社页面或知网详情页链接" />
                </Form.Item>
                <div className="form-grid">
                  <Form.Item {...restField} label="作者（可选）" name={[name, "authors_text"]} extra="多个作者用逗号或分号分隔。">
                    <Input placeholder="作者 A；作者 B" />
                  </Form.Item>
                  <Form.Item {...restField} label="DOI（可选）" name={[name, "doi"]}>
                    <Input placeholder="10.xxxx/xxxxx" />
                  </Form.Item>
                </div>
                <Form.Item {...restField} label="摘要（可选）" name={[name, "abstract"]}>
                  <Input.TextArea rows={3} placeholder="可粘贴来源页面中的摘要，全文仍以 PDF 为准" />
                </Form.Item>
                <Form.Item
                  {...restField}
                  label="全文 PDF"
                  name={[name, "pdf_file"]}
                  valuePropName="fileList"
                  getValueFromEvent={(event) => event?.fileList}
                  rules={[{ required: true, message: "请上传该文献的 PDF 全文。" }]}
                >
                  <Upload accept="application/pdf,.pdf" maxCount={1} beforeUpload={() => false}>
                    <Button icon={<UploadOutlined />}>选择 PDF（最大 50 MB）</Button>
                  </Upload>
                </Form.Item>
              </Card>
            ))}
            <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ source: "google_scholar", pdf_file: [] })} block>
              添加 Google Scholar / 知网文献
            </Button>
          </Space>
        )}
      </Form.List>

      <Divider />
      <Space wrap>
        <Button htmlType="submit" type="primary" size="large" loading={submitting} disabled={submitting} aria-label={submitting ? "正在提交调研任务" : undefined}>
          开始调研
        </Button>
        <span className="form-note">按 Ctrl+Enter 提交。</span>
      </Space>
    </Form>
  );
}