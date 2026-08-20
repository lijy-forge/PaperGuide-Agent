import { Alert, Button, Form, Input, InputNumber, Radio, Space, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import {
  createResearch,
  MAX_RESEARCH_QUESTION_LENGTH
} from "../api/research";
import type { ResearchRequest } from "../api/types";
import { addRecentTask, createLocalTitle } from "../utils/recentTasks";

export const MIN_RESEARCH_QUESTION_LENGTH = 10;

interface SubmissionError {
  message: string;
  hostOffline: boolean;
}

export function isValidMaxPapers(value: unknown): boolean {
  return Number.isInteger(value) && Number(value) >= 1 && Number(value) <= 50;
}

export function researchSubmissionError(error: unknown): SubmissionError {
  if (error instanceof ApiError) {
    if (error.code === "INVALID_REQUEST" || error.status === 422) {
      return {
        message: "请求无效，请检查调研问题和参数。",
        hostOffline: false
      };
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

export function ResearchForm({
  onSubmitted
}: {
  onSubmitted: (taskId: string) => void;
}) {
  const [form] = Form.useForm<ResearchRequest>();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<SubmissionError>();
  const submitLock = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function handleSubmit(values: ResearchRequest) {
    if (submitLock.current) return;
    submitLock.current = true;
    setSubmitting(true);
    setError(undefined);
    const payload: ResearchRequest = {
      ...values,
      question: values.question.trim()
    };
    try {
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
      initialValues={{ max_papers: 10, export_format: "markdown" }}
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
          description={
            error.hostOffline ? (
              <span>
                请运行：<Typography.Text code>paperpilot server start</Typography.Text>
              </span>
            ) : undefined
          }
          action={<Button onClick={() => form.submit()}>重试</Button>}
        />
      )}

      <Form.Item
        label="调研问题"
        name="question"
        rules={[
          { required: true, whitespace: true, message: "请输入调研问题。" },
          {
            validator: (_, value: string | undefined) => {
              const length = value?.trim().length ?? 0;
              if (length === 0) return Promise.resolve();
              if (length < MIN_RESEARCH_QUESTION_LENGTH) {
                return Promise.reject(
                  new Error(
                    `调研问题至少需要 ${MIN_RESEARCH_QUESTION_LENGTH} 个字符。`
                  )
                );
              }
              if (length > MAX_RESEARCH_QUESTION_LENGTH) {
                return Promise.reject(
                  new Error(
                    `调研问题不能超过 ${MAX_RESEARCH_QUESTION_LENGTH.toLocaleString()} 个字符。`
                  )
                );
              }
              return Promise.resolve();
            }
          }
        ]}
      >
        <Input.TextArea
          rows={7}
          maxLength={MAX_RESEARCH_QUESTION_LENGTH}
          showCount={{
            formatter: ({ count, maxLength }) => `${count} / ${maxLength}`
          }}
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
          extra="需要检索和分析的论文数量。"
          rules={[
            { required: true, message: "请选择最大论文数量。" },
            {
              validator: (_, value: unknown) =>
                isValidMaxPapers(value)
                  ? Promise.resolve()
                  : Promise.reject(new Error("论文数量必须在 1 到 50 之间。"))
            }
          ]}
        >
          <InputNumber min={1} max={50} precision={0} aria-label="最大论文数量" />
        </Form.Item>

        <Form.Item
          label="导出格式"
          name="export_format"
          rules={[{ required: true }]}
        >
          <Radio.Group aria-label="导出格式">
            <Radio.Button value="markdown">Markdown</Radio.Button>
            <Radio.Button value="html">HTML</Radio.Button>
            <Radio.Button value="pdf">PDF</Radio.Button>
          </Radio.Group>
        </Form.Item>
      </div>

      <Space wrap>
        <Button
          htmlType="submit"
          type="primary"
          size="large"
          loading={submitting}
          disabled={submitting}
          aria-label={submitting ? "正在提交调研任务" : undefined}
        >
          开始调研
        </Button>
        <span className="form-note">按 Ctrl+Enter 提交。</span>
      </Space>
    </Form>
  );
}
