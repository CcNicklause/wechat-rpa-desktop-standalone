import { useQuery } from '@tanstack/react-query';
import { requestLocalApi } from '../lib/api';

export interface LeadStats {
  total: number;
  by_status: Record<string, number>;
  success: number;
  running: number;
  failure: number;
  ts: string;
}

export function useLeadsStatsQuery(options?: { enabled?: boolean }) {
  return useQuery<LeadStats>({
    queryKey: ['leads-stats'],
    queryFn: async () => requestLocalApi<LeadStats>('/api/v1/leads/stats'),
    refetchInterval: 8000,
    enabled: options?.enabled ?? true,
    // 失败静默降级，不抛错
    retry: false,
    staleTime: 8000,
  });
}
