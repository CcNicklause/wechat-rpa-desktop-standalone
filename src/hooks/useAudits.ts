import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { requestLocalApi } from '../lib/api';
import { useLeadJobsStore, registerJobStarted } from './useLeadJobs';

export interface AuditLog {
  id: string;
  event_type: string;
  timestamp: string;
  result: string;
  message?: string;
  phone_masked?: string;
}

export function useAuditLogsQuery() {
  return useQuery<AuditLog[]>({
    queryKey: ['audits'],
    queryFn: () => requestLocalApi('/api/v1/audit'),
    refetchInterval: 8000, // 轮询审计流
  });
}

export function useExecuteRpaMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (leadId: string) =>
      requestLocalApi('/api/v1/rpa/add-wechat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ lead_id: leadId, dry_run: true })
      }),
    onSuccess: (response, leadId) => {
      // 成功触发后，失效 leads 状态及审计流，保证数据及时同步
      queryClient.invalidateQueries({ queryKey: ['leads'] });
      queryClient.invalidateQueries({ queryKey: ['audits'] });

      // Cycle 2：使用 registerJobStarted
      if (response.job_id) {
        registerJobStarted(leadId, response.job_id);
      }
    }
  });
}

// 手机号脱敏：13812345678 -> 138****5678
export function maskPhone(phone: string): string {
  if (!phone || phone.length < 7) return phone;
  return phone.slice(0, 3) + '****' + phone.slice(-4);
}

// 过滤出与指定手机号相关的审计记录
export function useLeadAudits(audits: AuditLog[], phone: string): AuditLog[] {
  const masked = maskPhone(phone);
  return audits.filter((a) => a.phone_masked === masked);
}

