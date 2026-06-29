export interface LeadDisplaySource {
  id?: string;
  lead_id?: string;
  account?: string | null;
  phone?: string | null;
  phone_masked?: string | null;
  remark?: string | null;
  add_reason?: string | null;
  customer_name?: string | null;
  name?: string | null;
}

export interface LeadDisplay {
  account: string;
  remark: string | null;
}

export function getLeadDisplay(lead: LeadDisplaySource): LeadDisplay {
  const account = firstText(lead.account, lead.phone, lead.phone_masked, lead.id, lead.lead_id) || '-';
  const remark = firstText(lead.remark, lead.add_reason, lead.customer_name, lead.name);

  return {
    account,
    remark: remark && remark !== account ? remark : null,
  };
}

function firstText(...values: Array<string | null | undefined>): string | null {
  for (const value of values) {
    const text = value?.trim();
    if (text) return text;
  }
  return null;
}
