export interface LeadVerificationSource {
  greeting?: string | null;
  verification_message?: string | null;
  verify_message?: string | null;
  add_reason?: string | null;
}

export function leadVerificationText(lead: LeadVerificationSource): string {
  return firstText(
    lead.greeting,
    lead.verification_message,
    lead.verify_message,
    lead.add_reason,
  ) || '未设置';
}

function firstText(...values: Array<string | null | undefined>): string | null {
  for (const value of values) {
    const text = value?.trim();
    if (text) return text;
  }
  return null;
}
