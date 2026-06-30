import { useState } from 'react';
import { LayoutDashboard, UserCheck, ShieldAlert, FlaskConical, Radio, LogOut, Bot, CircleUserRound } from 'lucide-react';
import { useAuthStore } from '@/stores/useAuthStore';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

// 路由集中定义在这里，AppShell + Sidebar 共用，新增/重命名都改这一处。
export const ROUTE_DEFINITIONS = [
  { path: '/dashboard', label: '系统看板', icon: LayoutDashboard },
  { path: '/accounts', label: '账号管理', icon: UserCheck },
  { path: '/risk', label: '风控管理', icon: ShieldAlert },
  { path: '/upstream', label: '上游对接', icon: Radio },
  { path: '/test', label: '开发测试', icon: FlaskConical },
] as const;

export type RoutePath = (typeof ROUTE_DEFINITIONS)[number]['path'];

interface SidebarProps {
  activePath: RoutePath;
  onNavigate: (next: RoutePath) => void;
}

export function Sidebar({
  activePath,
  onNavigate,
}: SidebarProps) {
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const [logoutDialogOpen, setLogoutDialogOpen] = useState(false);
  const displayName = user?.name || user?.phone || 'Guest';
  const displayPhone = user?.phone || '未绑定手机号';

  const handleLogoutClick = async () => {
    setLogoutDialogOpen(false);
    await logout();
  };

  return (
    <aside className="w-52 border-r border-border bg-card p-4 flex flex-col relative z-10">
      <div className="space-y-5">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-secondary text-secondary-foreground shadow-sm">
            <Bot className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-bold text-foreground">微信助手</h2>
            <div className="mt-1 flex items-center gap-1.5">
              <Badge variant="outline" className="text-[8px] px-1 py-0 h-3.5 leading-none shrink-0">
                {user?.role || 'agent'}
              </Badge>
            </div>
          </div>
        </div>

        <nav className="space-y-1.5">
          {ROUTE_DEFINITIONS.map((item) => {
            const Icon = item.icon;
            const isActive = activePath === item.path;
            return (
              // 用 <a href="#/path"> 让浏览器原生处理 hash 跳转：
              //   - 支持中键/Ctrl+Click 等用户预期；
              //   - 不阻断 Tauri / file:// 协议；
              //   - 同时 onClick + navigate() 保持显式路由调用 & a11y。
              <a
                key={item.path}
                href={`#${item.path}`}
                onClick={(e) => {
                  e.preventDefault();
                  onNavigate(item.path);
                }}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-semibold transition-colors text-left ${
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted/80 hover:text-foreground'
                }`}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span>{item.label}</span>
              </a>
            );
          })}
        </nav>
      </div>

      <div className="mt-auto border-t border-border/70 pt-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
            <CircleUserRound className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-semibold text-foreground">{displayName}</p>
            <p className="truncate text-[10px] text-muted-foreground">{displayPhone}</p>
          </div>
          <Dialog open={logoutDialogOpen} onOpenChange={setLogoutDialogOpen}>
            <TooltipProvider delayDuration={200}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    iconOnly
                    onClick={() => setLogoutDialogOpen(true)}
                    aria-label="安全退出"
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <LogOut className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">安全退出</TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <DialogContent className="max-w-sm">
              <DialogHeader>
                <DialogTitle>确认退出当前账号？</DialogTitle>
                <DialogDescription>
                  退出后需要重新登录才能继续操作本机微信助手。
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="outline">取消</Button>
                </DialogClose>
                <Button variant="destructive" onClick={handleLogoutClick}>
                  安全退出
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>
    </aside>
  );
}
