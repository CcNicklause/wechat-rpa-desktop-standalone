import { Card, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { AuditLog } from '@/hooks/useAudits';

interface AuditTimelineProps {
  audits: AuditLog[];
}

interface TranslatedAudit {
  displayTitle: string;
  displayMessage: string;
  displayResult: string;
}

// 将技术日志翻译为对用户友好的白话文
function translateAuditLog(audit: AuditLog): TranslatedAudit {
  let displayTitle = audit.event_type;
  let displayMessage = audit.message || '';
  
  // 1. 翻译 Event Type 作为标题
  switch (audit.event_type) {
    case 'wechat.friend.acceptance_checked':
      displayTitle = '🔍 检查加友状态';
      break;
    case 'wechat.friend.accepted':
      displayTitle = '🤝 好友添加成功';
      break;
    case 'wechat.friend.requested':
      displayTitle = '📨 好友申请已发送';
      break;
    case 'wechat.friend.add_requested':
      displayTitle = '⚡ 触发加好友指令';
      break;
    case 'rpa.real.started':
      displayTitle = '🤖 RPA 引擎启动';
      break;
    case 'rpa.real.completed':
      displayTitle = '✅ RPA 任务完成';
      break;
    case 'rpa.real.failed':
      displayTitle = '❌ RPA 任务失败';
      break;
    default:
      if (audit.event_type.startsWith('wechat.friend.')) {
        displayTitle = '💬 微信加友动态';
      } else if (audit.event_type.startsWith('rpa.')) {
        displayTitle = '⚙️ RPA 引擎指令';
      }
      break;
  }

  // 2. 翻译 Message 为易读白话文
  if (displayMessage.includes('|')) {
    // 原始格式类似于: "添加朋友|0|18325661362|朋友|添加到通讯录"
    const parts = displayMessage.split('|');
    if (parts[0] === '添加朋友') {
      const phone = parts[2] || '';
      displayMessage = `在微信客户端中定位并点击了账号 "${phone}"，发送好友申请。`;
    }
  } else if (audit.event_type === 'wechat.friend.acceptance_checked') {
    displayMessage = displayMessage || '系统已检查微信客户端中的好友状态，确认是否添加成功。';
  } else if (audit.event_type === 'wechat.friend.accepted') {
    displayMessage = displayMessage || '微信端已成功添加好友，对方已通过您的申请。';
  } else if (audit.event_type === 'wechat.friend.requested') {
    displayMessage = displayMessage || '好友验证申请已发送，正在等待对方通过。';
  } else if (audit.event_type === 'rpa.real.started') {
    displayMessage = `RPA 引擎已挂载微信客户端，开始执行自动化指令。`;
  } else if (audit.event_type === 'rpa.real.completed') {
    displayMessage = `RPA 流程执行完毕，已释放微信控制权。`;
  }

  // 3. 翻译结果状态
  let displayResult = audit.result || '';
  switch (audit.result) {
    case 'success':
      displayResult = '成功';
      break;
    case 'started':
      displayResult = '已启动';
      break;
    case 'approved':
      displayResult = '已批准';
      break;
    case 'pending':
      displayResult = '处理中';
      break;
    case 'failed':
      displayResult = '失败';
      break;
  }

  return {
    displayTitle,
    displayMessage: displayMessage || `${audit.phone_masked || ''} RPA 执行日志`,
    displayResult,
  };
}

export function AuditTimeline({ audits }: AuditTimelineProps) {
  return (
    <Card className="flex-1 flex flex-col p-6 shadow-sm border border-border overflow-hidden min-h-0">
      <CardTitle className="mb-4 pb-3 border-b border-border">📋 审计动态 Feed 时间轴</CardTitle>
      <div className="flex-1 overflow-y-auto space-y-4 pr-2 text-xs custom-scrollbar">
        {audits.map((audit) => {
          const { displayTitle, displayMessage, displayResult } = translateAuditLog(audit);
          return (
            <div key={audit.id} className="relative pl-6 pb-2 border-l border-border last:border-l-0">
              {/* Flat Slate point */}
              <div className="absolute -left-[6px] top-0.5 w-3 h-3 rounded-full bg-background border-2 border-primary flex items-center justify-center" />
              
              <div className="space-y-1">
                <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                  <span className="font-mono text-primary">
                    {audit.timestamp ? audit.timestamp.slice(11, 19) : '00:00:00'}
                  </span>
                  <Badge
                    variant={
                      audit.result === 'success' || audit.result === 'started' || audit.result === 'approved'
                        ? 'success'
                        : 'failed'
                    }
                  >
                    {displayResult}
                  </Badge>
                </div>
                <p className="text-[11px] font-semibold text-foreground">{displayTitle}</p>
                <p className="text-[10px] text-muted-foreground leading-relaxed">
                  {displayMessage}
                </p>
              </div>
            </div>
          );
        })}
        {audits.length === 0 && (
          <div className="text-center py-16 text-muted-foreground">
            <p className="text-xs">暂无审计事件</p>
          </div>
        )}
      </div>
    </Card>
  );
}
