export const LEAD_LIST_HINT = '按最近更新时间排序，点击线索查看执行步骤与日志';

export function leadListCountText(visibleCount: number, totalCount?: number | null): string {
  if (typeof totalCount === 'number' && totalCount >= visibleCount) {
    return `显示 ${visibleCount} / 共 ${totalCount}`;
  }
  return `显示 ${visibleCount} 条`;
}
