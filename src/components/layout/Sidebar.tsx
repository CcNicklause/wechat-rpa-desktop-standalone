import { LayoutDashboard, UserCheck, ShieldAlert, FlaskConical, Radio } from 'lucide-react';
import { useAuthStore } from '@/stores/useAuthStore';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

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

  return (
    <aside className="w-64 border-r border-border bg-card p-6 flex flex-col justify-between relative z-10">
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-secondary text-secondary-foreground rounded-lg shadow-sm">
            <span className="text-xl">🤖</span>
          </div>
          <div>
            <h2 className="text-sm font-bold text-foreground tracking-wide">WeChat RPA</h2>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-[10px] text-muted-foreground font-semibold">
                {user?.name || user?.phone || 'Guest'}
              </span>
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

      <Button variant="destructive" onClick={logout} className="w-full">
        安全退出
      </Button>
    </aside>
  );
}
