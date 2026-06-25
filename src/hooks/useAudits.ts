import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { requestLocalApi } from '../lib/api';

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
    mutationFn: (leadId: number) =>
      requestLocalApi('/api/v1/rpa/add-wechat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ lead_id: String(leadId), dry_run: true })
      }),
    onSuccess: () => {
      // 成功触发后，失效 leads 状态及审计流，保证数据及时同步
      queryClient.invalidateQueries({ queryKey: ['leads'] });
      queryClient.invalidateQueries({ queryKey: ['audits'] });
    }
  });
}
