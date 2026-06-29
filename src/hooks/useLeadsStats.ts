import { useQuery } from '@tanstack/react-query';
import { requestLocalApi } from '../lib/api';

export interface LeadStats {
  total: number;
  success: number;
  running: number;
  failed: number;
  neutral: number;
  status_counts: Record<string, number>;
}

export function useLeadsStatsQuery(enabled: boolean = true) {
  return useQuery<LeadStats>({
    queryKey: ['leadsStats'],
    queryFn: () => requestLocalApi('/api/v1/leads/stats'),
    refetchInterval: enabled ? 8000 : false,
    enabled,
  });
}
