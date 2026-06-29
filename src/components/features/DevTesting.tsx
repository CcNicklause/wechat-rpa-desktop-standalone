import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { FieldError } from '@/components/common/FieldError';
import { EmptyState } from '@/components/common/EmptyState';
import { StatusBadge } from '@/components/common/StatusBadge';
import { requestLocalApi } from '@/lib/api';
import { useToast } from '@/hooks/useToast';
import { useDevTestStore } from '@/stores/useDevTestStore';
import { registerJobStarted } from '@/hooks/useLeadJobs';
import { useHashRoute } from '@/hooks/useHashRoute';
import { JobProgress } from './JobProgress';

interface BatchLeadRow {
  lead_id: string;
  phone: string;
  customer_name: string;
  greeting: string;
}

interface SeedResponse {
  seeded: number;
  accepted_by_scheduler: number;
  scheduler_alive: boolean;
}

const DEFAULT_GREETING = '您好，我是销售顾问，收到了您的微信申请。';

function makeDefaultRow(index: number): BatchLeadRow {
  return {
    lead_id: `dev_mock_${Date.now()}_${index}`,
    phone: '',
    customer_name: '',
    greeting: DEFAULT_GREETING,
  };
}

function buildQuickFillRows(count: number): BatchLeadRow[] {
  return Array.from({ length: count }, (_, i) => {
    const ordinal = i + 1;
    return {
      lead_id: `dev_mock_lead_${ordinal}`,
      phone: `1380000000${ordinal}`,
      customer_name: `Mock 测试 ${ordinal}`,
      greeting: DEFAULT_GREETING,
    };
  });
}

const testSchema = z.object({
  phone: z.string().min(5, '手机号或微信号格式不符合验证规则'),
  greeting: z.string().min(1, '验证消息设置不能为空'),
  dryRun: z.boolean(),
});

type TestFormValues = z.infer<typeof testSchema>;

interface AuditEvent {
  event_type: string;
  timestamp: string;
  lead_id?: string | null;
  phone_masked?: string | null;
  result?: string | null;
  reason_code?: string | null;
  message?: string | null;
}

interface LeadSummary {
  lead_id: string;
  customer_name: string;
  phone_masked: string;
  status: string;
}

interface FriendCheckReport {
  lead_id: string;
  is_friend: boolean;
  status: string;
  attempts: number;
  last_error?: string | null;
  updated_at: string;
  customer_name?: string | null;
  account?: string | null;
  lead_status?: string | null;
}

interface FriendCheckReportsResponse {
  outbox: FriendCheckReport[];
  mock_upstream_reports: Array<{
    lead_id: string;
    is_friend: boolean;
    customer_name?: string | null;
    account?: string | null;
    lead_status?: string | null;
  }>;
}

const TEMPLATES = [
  { title: '模板 1：默认销售加微', text: '您好，我是销售顾问，收到了您的微信申请。' },
  { title: '模板 2：商务合作对接', text: '您好，我是 WeChat RPA 的对接人，想跟您进行商务合作。' },
  { title: '模板 3：极简打招呼', text: '您好，麻烦通过一下，谢谢！' },
];

export function DevTesting() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const { navigate } = useHashRoute('/dashboard');

  const [batchRows, setBatchRows] = useState<BatchLeadRow[]>([makeDefaultRow(0)]);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [simulatingLeadId, setSimulatingLeadId] = useState<string | null>(null);
  const [flushingReports, setFlushingReports] = useState(false);
  const [clearingPendingFriendLeads, setClearingPendingFriendLeads] = useState(false);
  const [manualFriendAccount, setManualFriendAccount] = useState('');
  const [manualFriendName, setManualFriendName] = useState('');
  const [manualSimulating, setManualSimulating] = useState(false);
  const [wipingData, setWipingData] = useState(false);

  const updateBatchRow = (index: number, patch: Partial<BatchLeadRow>) => {
    setBatchRows((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const addBatchRow = () => {
    setBatchRows((rows) => [...rows, makeDefaultRow(rows.length)]);
  };

  const removeBatchRow = (index: number) => {
    setBatchRows((rows) => (rows.length <= 1 ? rows : rows.filter((_, i) => i !== index)));
  };

  const fillFiveMockRows = () => {
    setBatchRows(buildQuickFillRows(5));
  };

  const submitBatch = async () => {
    const invalid = batchRows.some(
      (row) =>
        !row.lead_id.trim() ||
        row.phone.trim().length < 5 ||
        !row.customer_name.trim() ||
        !row.greeting.trim(),
    );
    if (invalid) {
      toast({
        title: '存在不合规的行',
        description: '请确保每一行 lead_id / phone / customer_name / greeting 都已填写，phone 至少 5 个字符。',
        variant: 'destructive',
      });
      return;
    }

    const confirmed = window.confirm(
      `⚠️ 即将下发 ${batchRows.length} 条线索到 mock 上游待发池，` +
        `并立即触发本地拉取与 RPA 队列执行。\n\n` +
        `本地 rpa_mode 决定后续是模拟还是真实加微（默认 real）。是否确认？`,
    );
    if (!confirmed) {
      toast({ title: '已取消', description: '未提交批量模拟线索', variant: 'default' });
      return;
    }

    setBatchSubmitting(true);
    try {
      const response = await requestLocalApi<SeedResponse>(
        '/api/v1/upstream/dev/seed-mock-leads',
        {
          method: 'POST',
          body: JSON.stringify({ leads: batchRows }),
        },
      );
      const skipped = response.seeded - response.accepted_by_scheduler;
      toast({
        title: `已下发 ${response.seeded} 条到 mock 上游`,
        description: `调度器接受 ${response.accepted_by_scheduler} 条，${skipped} 条被去重或终态跳过。请到「上游对接」页查看实时日志。`,
        variant: 'success',
      });
    } catch (err: any) {
      const message = err?.message || '';
      const isNetworkDown =
        err instanceof TypeError ||
        /Failed to fetch|NetworkError|ECONNREFUSED|Connection refused/i.test(message);
      toast({
        title: isNetworkDown ? '无法连接本地后端' : '批量下发失败',
        description: message || '请检查后端状态或上游模式（mock 才允许种子下发）',
        variant: 'destructive',
      });
    } finally {
      setBatchSubmitting(false);
    }
  };

  // 所有跨刷新需要保留的状态都进了 zustand store + persist；本组件只读不存 useState，
  // 这样即便表单意外触发原生提交导致整树重挂载，重新挂载后能立刻看到上次的 job/审计/表单值。
  const testJobId = useDevTestStore((s) => s.testJobId);
  const testLeadId = useDevTestStore((s) => s.testLeadId);
  const jobFinished = useDevTestStore((s) => s.jobFinished);
  const formDraft = useDevTestStore((s) => s.formDraft);
  const startJobInStore = useDevTestStore((s) => s.startJob);
  const markFinished = useDevTestStore((s) => s.markFinished);
  const clearJobInStore = useDevTestStore((s) => s.clearJob);
  const setFormDraft = useDevTestStore((s) => s.setFormDraft);

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<TestFormValues>({
    resolver: zodResolver(testSchema),
    defaultValues: formDraft,
  });

  const isDryRun = watch('dryRun');

  // 用 watch 订阅整表，把每一次变化写回 store；这样刷新后 form 也能恢复用户输入。
  useEffect(() => {
    const sub = watch((value) => {
      setFormDraft({
        phone: value.phone ?? '',
        greeting: value.greeting ?? '',
        dryRun: value.dryRun ?? true,
      });
    });
    return () => sub.unsubscribe();
  }, [watch, setFormDraft]);

  // 沿用老 frontend/app.js 的 refreshAudit 思路：按 lead_id 拉一段时间内的审计流，
  // 并在前端按时间倒序展示卡片。8s 轮询足以覆盖整条加微链路的事件刷新节奏。
  const auditQuery = useQuery<AuditEvent[]>({
    queryKey: ['dev-test-audit', testLeadId],
    enabled: !!testLeadId,
    refetchInterval: 8000,
    queryFn: () =>
      requestLocalApi<AuditEvent[]>(
        `/api/v1/audit?lead_id=${encodeURIComponent(testLeadId!)}&limit=200`,
      ),
  });

  const leadsQuery = useQuery<LeadSummary[]>({
    queryKey: ['dev-test-leads'],
    refetchInterval: 8000,
    queryFn: () => requestLocalApi<LeadSummary[]>('/api/v1/leads?limit=200'),
  });

  const friendReportsQuery = useQuery<FriendCheckReportsResponse>({
    queryKey: ['dev-test-friend-check-reports'],
    refetchInterval: 8000,
    queryFn: () =>
      requestLocalApi<FriendCheckReportsResponse>('/api/v1/upstream/dev/friend-check-reports?limit=100'),
  });

  const pendingFriendLeads = (leadsQuery.data ?? []).filter(
    (lead) => lead.status === 'WECHAT_ADD_REQUESTED',
  );

  const simulateFriendAccepted = async (leadId: string) => {
    setSimulatingLeadId(leadId);
    try {
      await requestLocalApi('/api/v1/friend-acceptance/dev/simulate-accepted', {
        method: 'POST',
        body: JSON.stringify({ lead_id: leadId }),
      });
      toast({
        title: '已模拟好友通过',
        description: `${leadId} 已写入本地好友确认与待上报队列`,
        variant: 'success',
      });
      queryClient.invalidateQueries({ queryKey: ['dev-test-leads'] });
      queryClient.invalidateQueries({ queryKey: ['dev-test-friend-check-reports'] });
      queryClient.invalidateQueries({ queryKey: ['dev-test-audit', leadId] });
    } catch (err: any) {
      toast({
        title: '模拟好友通过失败',
        description: err?.message || '请确认线索状态为 WECHAT_ADD_REQUESTED',
        variant: 'destructive',
      });
    } finally {
      setSimulatingLeadId(null);
    }
  };

  const flushFriendReports = async () => {
    setFlushingReports(true);
    try {
      const res = await requestLocalApi<any>('/api/v1/upstream/dev/trigger-friend-check-report', {
        method: 'POST',
      });
      toast({
        title: '好友对账上报已触发',
        description: `成功 ${res.reported ?? 0} 条，失败 ${res.failed ?? 0} 条`,
        variant: (res.failed ?? 0) > 0 ? 'destructive' : 'success',
      });
      queryClient.invalidateQueries({ queryKey: ['dev-test-friend-check-reports'] });
    } catch (err: any) {
      toast({
        title: '触发好友对账上报失败',
        description: err?.message || '请确认上游调度器已启动',
        variant: 'destructive',
      });
    } finally {
      setFlushingReports(false);
    }
  };

  const clearPendingFriendLeads = async () => {
    if (pendingFriendLeads.length === 0) {
      toast({
        title: '暂无待清理线索',
        description: '当前没有 WECHAT_ADD_REQUESTED 状态的线索',
        variant: 'default',
      });
      return;
    }

    const confirmed = window.confirm(
      `即将把 ${pendingFriendLeads.length} 条 WECHAT_ADD_REQUESTED 线索标记为 RPA_BLOCKED，空闲对账将不再扫描它们。是否继续？`,
    );
    if (!confirmed) {
      return;
    }

    setClearingPendingFriendLeads(true);
    try {
      const res = await requestLocalApi<{ cleared: number; to_status: string }>(
        '/api/v1/friend-acceptance/dev/clear-pending',
        { method: 'POST' },
      );
      toast({
        title: '已清理待对账线索',
        description: `共清理 ${res.cleared ?? 0} 条，状态已置为 ${res.to_status ?? 'RPA_BLOCKED'}`,
        variant: 'success',
      });
      queryClient.invalidateQueries({ queryKey: ['dev-test-leads'] });
      queryClient.invalidateQueries({ queryKey: ['dev-test-friend-check-reports'] });
    } catch (err: any) {
      toast({
        title: '清理待对账线索失败',
        description: err?.message || '请确认后端已加载新的开发测试接口',
        variant: 'destructive',
      });
    } finally {
      setClearingPendingFriendLeads(false);
    }
  };

  const wipeAllData = async () => {
    // 二次确认（危险操作）：第一轮说明范围与不可逆性，第二轮要求显式输入确认口令。
    const first = window.confirm(
      '⚠️ 危险操作：即将清空本地全部业务数据\n\n' +
        '清理范围：线索 / RPA 任务 / 审计事件 / 好友对账 / 加微结果上报 / 每日计数。\n' +
        '保留：上游配置（upstream_config）等配置，清空后仍可直接使用。\n\n' +
        '此操作不可恢复，且会同步清空调度器内存队列。是否继续？',
    );
    if (!first) {
      toast({ title: '已取消', description: '未清空本地数据', variant: 'default' });
      return;
    }
    const second = window.prompt('确认清空请输入：清空');
    if (second !== '清空') {
      toast({ title: '已取消', description: '确认口令不匹配，未清空本地数据', variant: 'default' });
      return;
    }

    setWipingData(true);
    try {
      const res = await requestLocalApi<{ status: string; counts: Record<string, number>; queue_cleared: boolean }>(
        '/api/v1/upstream/dev/wipe-data',
        { method: 'POST' },
      );
      const total = Object.values(res.counts ?? {}).reduce((acc, n) => acc + (n || 0), 0);
      toast({
        title: '已清空本地业务数据',
        description: `共删除 ${total} 条记录，队列已${res.queue_cleared ? '清空' : '跳过'}（上游配置已保留）`,
        variant: 'success',
      });
      // 清空 DevTest store 里残留的 job/表单快照，避免 UI 还指向已不存在的 job
      clearJobInStore();
      queryClient.invalidateQueries({ queryKey: ['dev-test-leads'] });
      queryClient.invalidateQueries({ queryKey: ['dev-test-friend-check-reports'] });
      queryClient.invalidateQueries({ queryKey: ['dev-test-audit', testLeadId] });
    } catch (err: any) {
      const message = err?.message || '';
      const isNetworkDown =
        err instanceof TypeError ||
        /Failed to fetch|NetworkError|ECONNREFUSED|Connection refused/i.test(message);
      toast({
        title: isNetworkDown ? '无法连接本地后端' : '清空本地数据失败',
        description: message || '请确认本地后端已启动',
        variant: 'destructive',
      });
    } finally {
      setWipingData(false);
    }
  };

  const simulateManualFriendAccepted = async (flushAfter: boolean) => {
    const account = manualFriendAccount.trim();
    if (account.length < 5) {
      toast({
        title: '请输入账号',
        description: '账号至少 5 个字符，用于创建开发测试好友对账线索',
        variant: 'destructive',
      });
      return;
    }

    setManualSimulating(true);
    try {
      const res = await requestLocalApi<any>('/api/v1/friend-acceptance/dev/simulate-accepted', {
        method: 'POST',
        body: JSON.stringify({
          account,
          customer_name: manualFriendName.trim() || account,
        }),
      });
      if (flushAfter) {
        await requestLocalApi('/api/v1/upstream/dev/trigger-friend-check-report', {
          method: 'POST',
        });
      }
      toast({
        title: flushAfter ? '已模拟并立即上报' : '已模拟已是好友账号',
        description: `${res.lead_id || account} 已进入好友对账链路`,
        variant: 'success',
      });
      queryClient.invalidateQueries({ queryKey: ['dev-test-leads'] });
      queryClient.invalidateQueries({ queryKey: ['dev-test-friend-check-reports'] });
    } catch (err: any) {
      const message = err?.message || '';
      const endpointMissing = /API Error 404|Not Found/i.test(message);
      toast({
        title: '手动账号模拟失败',
        description: endpointMissing
          ? '后端还没加载新的模拟接口，请重启 Python 后端或重新运行 pnpm tauri dev'
          : message || '请确认后端和上游调度器已启动',
        variant: 'destructive',
      });
    } finally {
      setManualSimulating(false);
    }
  };

  const handleSelectTemplate = (val: string) => {
    setValue('greeting', val, { shouldDirty: true });
    setFormDraft({ greeting: val });
  };

  const onSubmit = async (data: TestFormValues) => {
    // 开发测试页保留前端确认，避免误触真实微信自动化；真实上游队列不需要人工确认。
    if (!data.dryRun) {
      const confirmed = window.confirm(
        `⚠️ 即将执行【真实加微】操作\n\n目标：${data.phone}\n验证语：${data.greeting}\n\n后端会接管 Windows 引擎对微信客户端发送真实指令，是否确认继续？`,
      );
      if (!confirmed) {
        toast({ title: '已取消', description: '用户取消了真实加微执行', variant: 'default' });
        return;
      }
    }

    try {
      // 1. Create a dynamic test lead to satisfy backend validation
      const lead = await requestLocalApi<any>('/api/v1/leads', {
        method: 'POST',
        body: JSON.stringify({
          customer_name: '测试用户',
          company: '测试开发公司',
          phone: data.phone,
          sales_id: 'sales_demo_001',
        }),
      });

      // 1.5. Start call to transition lead state to CALLING
      await requestLocalApi<any>(`/api/v1/leads/${lead.lead_id}/call-start`, {
        method: 'POST',
      });

      // 2. Submit call summary to approve/consent lead
      await requestLocalApi<any>(`/api/v1/leads/${lead.lead_id}/call-summary`, {
        method: 'POST',
        body: JSON.stringify({
          intent: 'STRONG',
          summary: '开发测试自动生成的通话总结',
          customer_consent: true,
          sales_confirmed_call: true,
          consent_evidence: '手动测试线索自动授权同意',
        }),
      });

      // 3. Trigger RPA task
      // human_approval 仅作为审计字段保留；后端真实队列不再要求人工二次确认。
      const response = await requestLocalApi<any>('/api/v1/rpa/add-wechat', {
        method: 'POST',
        body: JSON.stringify({
          lead_id: lead.lead_id,
          greeting: data.greeting,
          dry_run: data.dryRun,
          human_approval: !data.dryRun,
        }),
      });

      if (response.job_id) {
        // 2.5. Register job in useLeadJobs store for board visibility
        registerJobStarted(lead.lead_id, response.job_id);

        // 一次性把 job_id / lead_id / 表单值写入 store，立刻持久到 localStorage
        startJobInStore({
          jobId: response.job_id,
          leadId: lead.lead_id,
          form: { phone: data.phone, greeting: data.greeting, dryRun: data.dryRun },
        });
        toast({
          title: data.dryRun ? '模拟任务已启动' : '真实加微任务已下发',
          description: data.dryRun
            ? '模拟加微指令已进入队列，可在右侧查看步骤'
            : '真实 RPA 指令已下发，请保持微信客户端可见',
          variant: 'success',
        });
      }
      // 立刻拉一次审计，避免等到下一次轮询窗口
      queryClient.invalidateQueries({ queryKey: ['dev-test-audit', lead.lead_id] });
    } catch (err: any) {
      // 区分"后端没起来 / 网络不通"和"后端返回错误"两种情况，给开发更明确的提示
      const message = err?.message || '';
      const isNetworkDown =
        err instanceof TypeError ||
        /Failed to fetch|NetworkError|ECONNREFUSED|Connection refused/i.test(message);

      if (isNetworkDown) {
        toast({
          title: '无法连接本地后端',
          description: '本地 Python 后端未响应，请确认桌面端已启动并完成 RPA 引擎初始化。',
          variant: 'destructive',
        });
      } else {
        toast({
          title: '执行测试失败',
          description: message || '通信阻断或配置参数超限',
          variant: 'destructive',
        });
      }
    }
  };

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-6 space-y-6">
      <Card className="p-4 shadow-sm border border-destructive/40 bg-destructive/5">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="space-y-1 min-w-0">
            <h3 className="font-semibold text-xs text-destructive tracking-wider">🧹 一键清空本地数据（危险操作）</h3>
            <p className="text-[11px] text-muted-foreground">
              清空线索 / RPA 任务 / 审计 / 好友对账 / 加微上报 / 每日计数，保留上游配置。可清掉僵尸中间态残留（如 CALLING/RPA_SIMULATED）及全部业务数据回到干净态，但不可恢复，需二次确认。
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="destructive"
            disabled={wipingData}
            onClick={wipeAllData}
            className="shrink-0"
          >
            {wipingData ? '清空中…' : '⚠️ 一键清空本地数据'}
          </Button>
        </div>
      </Card>

      <Card className="p-6 shadow-sm border border-border bg-card">
        <CardHeader className="p-0 pb-4 border-b border-border mb-4">
          <CardTitle>批量线索模拟（走真实上游链路）</CardTitle>
        </CardHeader>
        <CardContent className="p-0 space-y-3 text-xs">
          <p className="text-[11px] text-muted-foreground">
            每一行代表一条上游下发的线索。提交后会进入 mock 上游待发池并立即触发一次拉取，
            后续可在「上游对接」页观察日志、状态和队列。当前 rpa_mode 由后端 .env 决定（默认 real）。
          </p>

          <div className="space-y-2">
            <div className="grid grid-cols-[1.2fr_1fr_1fr_1.5fr_auto] gap-2 text-[10px] font-semibold uppercase text-muted-foreground">
              <span>lead_id</span>
              <span>phone</span>
              <span>customer_name</span>
              <span>greeting</span>
              <span></span>
            </div>
            {batchRows.map((row, index) => (
              <div
                key={index}
                className="grid grid-cols-[1.2fr_1fr_1fr_1.5fr_auto] gap-2 items-start"
              >
                <Input
                  type="text"
                  value={row.lead_id}
                  onChange={(e) => updateBatchRow(index, { lead_id: e.target.value })}
                  placeholder="dev_mock_..."
                  className="h-7 px-2 py-1"
                />
                <Input
                  type="text"
                  value={row.phone}
                  onChange={(e) => updateBatchRow(index, { phone: e.target.value })}
                  placeholder="138..."
                  className="h-7 px-2 py-1"
                />
                <Input
                  type="text"
                  value={row.customer_name}
                  onChange={(e) => updateBatchRow(index, { customer_name: e.target.value })}
                  placeholder="测试用户"
                  className="h-7 px-2 py-1"
                />
                <Input
                  type="text"
                  value={row.greeting}
                  onChange={(e) => updateBatchRow(index, { greeting: e.target.value })}
                  placeholder="验证语"
                  className="h-7 px-2 py-1"
                />
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => removeBatchRow(index)}
                  disabled={batchRows.length <= 1}
                  className="h-7 px-2 text-[10px]"
                >
                  删除
                </Button>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-2 pt-2">
            <Button type="button" size="sm" variant="outline" onClick={addBatchRow}>
              + 新增一行
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={fillFiveMockRows}>
              快速填 5 条 mock
            </Button>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              onClick={submitBatch}
              disabled={batchSubmitting}
              className="ml-auto"
            >
              {batchSubmitting ? '正在下发…' : '⚠️ 一键模拟下发'}
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,3fr)_minmax(320px,2fr)] gap-6 items-start pb-6">
      <Card className="min-w-0 flex flex-col p-6 shadow-sm border border-border bg-card">
        <CardHeader className="p-0 pb-4 border-b border-border mb-4">
          <CardTitle>手动加友功能测试面板</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <form
            // 显式拦截原生提交，防止 Tauri webview 把表单 action="" 当作页面 reload，
            // 导致 AppShell 整树重挂载、hash 路由被默认值覆盖到 #/dashboard。
            onSubmit={(e) => {
              e.preventDefault();
              e.stopPropagation();
              // 把当前表单值同步写到 store，确保哪怕之后真出了 reload，重新挂载后
              // form 默认值也是用户最后看到的那一份。
              const v = getValues();
              setFormDraft({ phone: v.phone, greeting: v.greeting, dryRun: v.dryRun });
              void handleSubmit(onSubmit)(e);
            }}
            noValidate
            className="space-y-4 text-xs"
          >
            <div className="space-y-1.5">
              <Label>测试手机号 / 微信号</Label>
              <Input
                type="text"
                {...register('phone')}
                placeholder="请输入手机号或者微信号"
              />
              {errors.phone && <FieldError>{errors.phone.message}</FieldError>}
            </div>

            <div className="space-y-1.5">
              <Label>常用验证模板预设</Label>
              <Select
                onChange={(e) => handleSelectTemplate(e.target.value)}
              >
                {TEMPLATES.map((t, idx) => (
                  <option key={idx} value={t.text}>{t.title}</option>
                ))}
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label>验证语设置</Label>
              <Textarea
                {...register('greeting')}
                rows={3}
              />
              {errors.greeting && <FieldError>{errors.greeting.message}</FieldError>}
            </div>

            <div className="flex justify-between items-center border border-border p-3 bg-muted/20 rounded-xl">
              <div className="space-y-0.5">
                <span className="font-semibold text-foreground">Dry Run (模拟微信点击操作)</span>
                <p className="text-[10px] text-muted-foreground">开启后仅展示模拟点击，关闭后将接管 Windows 引擎执行真实指令</p>
              </div>
              <Switch
                checked={isDryRun}
                onCheckedChange={(checked) => setValue('dryRun', checked, { shouldDirty: true })}
              />
            </div>

            <Button
              type="submit"
              disabled={isSubmitting || (!!testJobId && !jobFinished)}
              variant={isDryRun ? 'default' : 'destructive'}
              className="w-full h-9"
            >
              {isDryRun ? '立即执行模拟加友测试' : '⚠️ 立即执行真实加微（需确认）'}
            </Button>
          </form>
        </CardContent>
      </Card>

      <div className="min-w-0 flex flex-col gap-6">
        <Card className="min-h-[236px] p-6 border border-border bg-card flex flex-col gap-4">
          <div className="flex items-center justify-between pb-3 border-b border-border">
            <h3 className="font-semibold text-xs text-foreground tracking-wider">🧪 运行测试反馈控制台</h3>
            <div className="flex gap-1">
              {testJobId && (
                <Button
                  size="sm"
                  variant="outline"
                  type="button"
                  className="h-6 px-2 text-[10px]"
                  onClick={() => navigate('/dashboard', { lead: testLeadId, job: testJobId, tab: 'overview' })}
                >
                  在看板查看
                </Button>
              )}
              {testJobId && jobFinished && (
                <Button
                  size="sm"
                  variant="outline"
                  type="button"
                  className="h-6 px-2 text-[10px]"
                  onClick={clearJobInStore}
                >
                  清空
                </Button>
              )}
            </div>
          </div>
          {testJobId ? (
            <JobProgress
              jobId={testJobId}
              // 终态回调只标记 finished，不卸载组件、不动 store 里的 lastSnapshot，
              // 保证刷新前后用户都能看到完整 step 流水。
              onComplete={markFinished}
            />
          ) : (
            <EmptyState
              variant="fill"
              icon="🔬"
              title="暂无测试进程运行"
              description={'配置左侧参数后点击"立即执行加友测试"即可捕获并监听本地指令'}
            />
          )}
        </Card>

        <Card className="min-h-[236px] max-h-[420px] p-6 border border-border bg-card flex flex-col gap-3 overflow-hidden">
          <div className="flex items-center justify-between pb-3 border-b border-border">
            <h3 className="font-semibold text-xs text-foreground tracking-wider">📒 审计事件</h3>
            <Button
              size="sm"
              variant="outline"
              type="button"
              className="h-6 px-2 text-[10px]"
              disabled={!testLeadId || auditQuery.isFetching}
              onClick={() => auditQuery.refetch()}
            >
              {auditQuery.isFetching ? '刷新中…' : '刷新审计'}
            </Button>
          </div>

          <AuditEventList
            leadId={testLeadId}
            events={auditQuery.data ?? []}
            isLoading={auditQuery.isLoading}
            error={auditQuery.error as Error | null}
          />
        </Card>

        <Card className="p-6 border border-border bg-card flex flex-col gap-3">
          <div className="flex items-center justify-between gap-2 pb-3 border-b border-border">
            <h3 className="font-semibold text-xs text-foreground tracking-wider">🤝 好友通过模拟 / 对账</h3>
            <Button
              size="sm"
              variant="outline"
              type="button"
              className="h-6 px-2 text-[10px] ml-auto"
              disabled={clearingPendingFriendLeads || pendingFriendLeads.length === 0}
              onClick={clearPendingFriendLeads}
            >
              {clearingPendingFriendLeads ? '清理中...' : '清理待对账'}
            </Button>
            <Button
              size="sm"
              variant="outline"
              type="button"
              className="h-6 px-2 text-[10px]"
              disabled={flushingReports}
              onClick={flushFriendReports}
            >
              {flushingReports ? '上报中...' : '立即上报'}
            </Button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-2">
            <div className="space-y-1">
              <Label className="text-[10px]">已是好友账号</Label>
              <Input
                type="text"
                value={manualFriendAccount}
                onChange={(e) => setManualFriendAccount(e.target.value)}
                placeholder="输入微信号/手机号"
                className="h-7 px-2 py-1.5 text-[11px]"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-[10px]">账号昵称</Label>
              <Input
                type="text"
                value={manualFriendName}
                onChange={(e) => setManualFriendName(e.target.value)}
                placeholder="例如：张三"
                className="h-7 px-2 py-1.5 text-[11px]"
              />
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 text-[10px]"
              disabled={manualSimulating}
              onClick={() => simulateManualFriendAccepted(false)}
            >
              {manualSimulating ? '处理中...' : '模拟已是好友'}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="default"
              className="h-7 text-[10px]"
              disabled={manualSimulating}
              onClick={() => simulateManualFriendAccepted(true)}
            >
              模拟并立即上报测试
            </Button>
          </div>

          <div className="space-y-2">
            <p className="text-[10px] font-semibold text-muted-foreground">待通过线索</p>
            {pendingFriendLeads.length === 0 ? (
              <p className="text-[11px] text-muted-foreground">暂无 WECHAT_ADD_REQUESTED 线索</p>
            ) : (
              pendingFriendLeads.slice(0, 5).map((lead) => (
                <div
                  key={lead.lead_id}
                  className="flex items-center justify-between gap-2 border border-border rounded-lg bg-muted/20 px-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="text-[11px] font-semibold text-foreground truncate">{lead.customer_name}</p>
                    <p className="text-[10px] text-muted-foreground font-mono truncate">
                      {lead.lead_id} · {lead.phone_masked}
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-[10px] shrink-0"
                    disabled={simulatingLeadId === lead.lead_id}
                    onClick={() => simulateFriendAccepted(lead.lead_id)}
                  >
                    {simulatingLeadId === lead.lead_id ? '模拟中' : '模拟已通过'}
                  </Button>
                </div>
              ))
            )}
          </div>

          <div className="space-y-2">
            <p className="text-[10px] font-semibold text-muted-foreground">本地待上报 / 上报结果</p>
            {(friendReportsQuery.data?.outbox ?? []).length === 0 ? (
              <p className="text-[11px] text-muted-foreground">暂无好友对账记录</p>
            ) : (
              <div className="space-y-1.5 max-h-36 overflow-y-auto pr-1">
                {(friendReportsQuery.data?.outbox ?? []).map((report) => (
                  <div
                    key={report.lead_id}
                    className="flex items-center justify-between gap-2 border border-border rounded-lg px-2 py-1.5 text-[10px]"
                  >
                    <span className="min-w-0 truncate">
                      <span className="font-semibold text-foreground">
                        {report.customer_name || report.account || report.lead_id}
                      </span>
                      <span className="text-muted-foreground font-mono"> · {report.lead_id}</span>
                    </span>
                    <StatusBadge
                      status={report.status}
                      showDot
                      className="shrink-0 text-[10px]"
                    />
                  </div>
                ))}
              </div>
            )}
            <p className="text-[10px] text-muted-foreground">
              mock 上游已收到 {friendReportsQuery.data?.mock_upstream_reports.length ?? 0} 条好友对账。
            </p>
            {(friendReportsQuery.data?.mock_upstream_reports ?? []).length > 0 && (
              <div className="space-y-1.5 max-h-28 overflow-y-auto pr-1">
                {(friendReportsQuery.data?.mock_upstream_reports ?? []).slice().reverse().map((report, index) => (
                  <div
                    key={`${report.lead_id}-${index}`}
                    className="border border-border rounded-lg px-2 py-1.5 text-[10px] bg-muted/20"
                  >
                    <p className="font-semibold text-foreground truncate">
                      {report.customer_name || report.account || report.lead_id}
                    </p>
                    <p className="font-mono text-muted-foreground truncate">
                      {report.lead_id} · is_friend={String(report.is_friend)}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      </div>
      </div>
    </div>
  );
}

// 沿用老 frontend/index.html#auditCards 的卡片结构：event_type + timestamp、message、
// 以及 result/reason_code/phone_masked 标签。新版去掉了老页面里那些手动按钮触发的
// "创建线索 / 开始通话 / 提交小结" 步骤事件展示——这些现在已经由"立即执行"按钮
// 一键自动完成，不再需要单独可视化每一步。
function AuditEventList({
  leadId,
  events,
  isLoading,
  error,
}: {
  leadId: string | null;
  events: AuditEvent[];
  isLoading: boolean;
  error: Error | null;
}) {
  if (!leadId) {
    return (
      <EmptyState
        variant="fill"
        icon="🗂️"
        title="暂无审计事件"
        description="执行测试后会按 lead_id 拉取本次测试相关的审计流"
      />
    );
  }

  if (error) {
    return <FieldError className="text-[11px]">❌ {error.message}</FieldError>;
  }

  if (isLoading && events.length === 0) {
    return <p className="text-[11px] text-muted-foreground">正在加载审计事件…</p>;
  }

  if (events.length === 0) {
    return <p className="text-[11px] text-muted-foreground">暂未捕获到事件</p>;
  }

  // 后端默认按 timestamp 升序返回；测试控制台希望最近的事件在最上面
  const sorted = [...events].sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));

  return (
    <div className="flex-1 overflow-y-auto space-y-2 pr-1">
      {sorted.map((ev, idx) => (
        <article
          key={`${ev.event_type}-${ev.timestamp}-${idx}`}
          className="border border-border rounded-xl p-3 bg-muted/20"
        >
          <header className="flex justify-between gap-2 items-center">
            <strong className="text-xs text-foreground break-all">{ev.event_type}</strong>
            <time className="text-[10px] text-muted-foreground whitespace-nowrap">
              {formatTimestamp(ev.timestamp)}
            </time>
          </header>
          <p className="mt-1.5 text-[11px] text-foreground/80">
            {ev.message || ev.reason_code || '无消息'}
          </p>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {ev.result && <MetaPill tone={resultTone(ev.result)}>结果 {ev.result}</MetaPill>}
            {ev.reason_code && <MetaPill>原因 {ev.reason_code}</MetaPill>}
            {ev.phone_masked && <MetaPill>{ev.phone_masked}</MetaPill>}
          </div>
        </article>
      ))}
    </div>
  );
}

const META_TONE_VARIANT: Record<'default' | 'success' | 'warn' | 'fail', 'secondary' | 'success' | 'pending' | 'failed'> = {
  default: 'secondary',
  success: 'success',
  warn: 'pending',
  fail: 'failed',
};

function MetaPill({ children, tone = 'default' }: { children: React.ReactNode; tone?: 'default' | 'success' | 'warn' | 'fail' }) {
  return (
    <Badge variant={META_TONE_VARIANT[tone]} className="px-1.5 py-0.5 text-[10px]">
      {children}
    </Badge>
  );
}

function resultTone(result: string): 'default' | 'success' | 'warn' | 'fail' {
  const r = result.toLowerCase();
  if (r === 'success' || r === 'accepted' || r === 'approved') return 'success';
  if (r === 'failed' || r === 'blocked') return 'fail';
  if (r === 'pending' || r === 'queued' || r === 'started' || r === 'business_outcome') return 'warn';
  return 'default';
}

function formatTimestamp(ts: string): string {
  // 后端写的是 ISO-8601 with timezone；展示时只保留 HH:mm:ss，便于在窄列里阅读。
  // 解析失败时原样返回，避免吃掉调试线索。
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
