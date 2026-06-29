# Frontend Leads Board 开发周期

## Cycle 1: 基础组件与数据层完善
- 创建 Drawer 组件
- 创建 board 目录结构
- 实现 KpiStrip 组件
- 实现 AuditList 可复用组件
- 实现 JobStepsView 可复用组件
- 更新 useHashRoute（已完成）
- 更新 useJobSnapshot（已完成）
- 更新 useLeadJobs（已完成）
- 更新 auditTranslate（已完成）

## Cycle 2: 主看板与抽屉骨架
- 实现 LeadsBoard 主组件
- 重构 LeadsList 支持选中状态
- 实现 LeadDetailDrawer 容器
- 实现 LeadHeader 组件
- 实现基础 Tab 切换

## Cycle 3: Tab 内容与实时更新
- 实现 LeadJobsPanel（历史任务列表）
- 实现 LeadStepsPanel（步骤流）
- 实现 LeadTimelinePanel（审计时间线）
- 实现 LeadRawPanel（原始数据）
- 实现 LeadRowSummary（行内子文案）
- 触发执行后自动打开抽屉

## Cycle 4: 兼容性与持久化
- 重构 JobProgress 为薄壳
- 重构 AuditTimeline 为薄壳
- 更新 LeadsDashboard 保持兼容
- 完善 localStorage 持久化策略
- 类型检查与构建验证
