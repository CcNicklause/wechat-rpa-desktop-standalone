import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { requestLocalApi } from '../lib/api';
import type { LeadDisplaySource } from '@/lib/leadDisplay';

export interface Lead extends LeadDisplaySource {
  id: string;
  phone: string;
  status: string;
  name?: string;
  account?: string;
  remark?: string;
  customer_name?: string;
  phone_masked?: string;
  add_reason?: string;
  source?: string;
}

export function useLeadsQuery(enabled: boolean = true) {
  return useQuery<Lead[]>({
    queryKey: ['leads'],
    queryFn: async () => {
      const leads = await requestLocalApi<Lead[]>('/api/v1/leads');
      return leads.map(normalizeLead);
    },
    refetchInterval: enabled ? 8000 : false, // 只有在需要时（比如已登录）进行轮询
  });
}

export function normalizeLead(lead: Lead): Lead {
  const id = lead.id || lead.lead_id || '';
  const phone = lead.phone || lead.account || lead.phone_masked || '';
  const name = lead.name || lead.customer_name || lead.remark || '';

  return {
    ...lead,
    id,
    phone,
    name,
  };
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
