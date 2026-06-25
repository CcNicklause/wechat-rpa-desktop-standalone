import { Sun, Moon } from 'lucide-react';
import { useTheme } from '@/hooks/useTheme';
import { Button } from '@/components/ui/button';

export function DashboardHeader() {
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="h-16 border-b border-border bg-card flex items-center justify-between px-8">
      <div className="space-y-0.5">
        <h1 className="text-sm font-bold text-foreground">自动化运行仪表盘</h1>
        <p className="text-[10px] text-muted-foreground">本地 SQLite 与 Windows 引擎同步监控</p>
      </div>
      <div className="flex items-center gap-4">
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          className="h-8 w-8 rounded-lg"
          title="切换主题"
        >
          {theme === 'dark' ? (
            <Sun className="h-4 w-4 text-amber-400" />
          ) : (
            <Moon className="h-4 w-4 text-slate-600" />
          )}
        </Button>
        <div className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 bg-emerald-500 rounded-full" />
          <span className="text-[10px] text-muted-foreground font-mono">CONNECTED NODE v0.1.0</span>
        </div>
      </div>
    </header>
  );
}
