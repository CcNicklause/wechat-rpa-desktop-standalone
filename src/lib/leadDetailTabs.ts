export type LeadDetailTab = 'overview' | 'process' | 'history';

export const LEAD_DETAIL_TAB_LABELS: Record<LeadDetailTab, string> = {
  overview: '概览',
  process: '过程',
  history: '历史',
};

export function normalizeLeadDetailTab(tab?: string | null): LeadDetailTab {
  if (tab === 'overview' || tab === 'process' || tab === 'history') return tab;
  if (tab === 'jobs') return 'history';
  if (tab === 'steps' || tab === 'timeline' || tab === 'raw') return 'process';
  return 'overview';
}
