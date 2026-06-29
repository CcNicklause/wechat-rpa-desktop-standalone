import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { requestLocalApi } from '../lib/api';

export interface Lead {
  id: string;
  name: string;
  phone: string;
  status: string;
  add_reason?: string;
  source?: string;
}

export function useLeadsQuery(enabled: boolean = true) {
  return useQuery<Lead[]>({
    queryKey: ['leads'],
    queryFn: () => requestLocalApi('/api/v1/leads'),
    refetchInterval: enabled ? 8000 : false, // 只有在需要时（比如已登录）进行轮询
  });
}

export function useAddLeadMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (newLead: Omit<Lead, 'id' | 'status'>) => 
      requestLocalApi('/api/v1/leads', {
        method: 'POST',
        body: JSON.stringify(newLead)
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['leads'] });
    }
  });
}

export function usePrecheckMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (leadId: string) =>
      requestLocalApi('/api/v1/rpa/precheck', {
        method: 'POST',
        body: JSON.stringify({ lead_id: leadId })
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['leads'] });
    }
  });
}
