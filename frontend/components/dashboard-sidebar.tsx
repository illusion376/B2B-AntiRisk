'use client';

import { BookOpenCheck, ChevronRight, CircleHelp, History, LayoutDashboard, Plus, Settings2, ShieldCheck, X } from 'lucide-react';
import type { User, View } from '@/lib/types';

interface Props {
  view: View;
  user: User | null;
  projectCount: number;
  ruleCount: number;
  open: boolean;
  onClose: () => void;
  onNavigate: (view: View) => void;
  onCreate: () => void;
  onHelp: () => void;
}

export function DashboardSidebar({view,user,projectCount,ruleCount,open,onClose,onNavigate,onCreate,onHelp}: Props) {
  const items = [
    {view:'documents' as const,label:'Документы',Icon:LayoutDashboard,count:projectCount},
    {view:'rules' as const,label:'Правила проверки',Icon:BookOpenCheck,count:ruleCount},
    {view:'history' as const,label:'История действий',Icon:History,count:null},
    {view:'settings' as const,label:'Настройки',Icon:Settings2,count:null},
  ];
  return <>
    {open && <button className="dashboard-scrim" aria-label="Закрыть меню" onClick={onClose} />}
    <aside className={`dashboard-sidebar ${open?'is-open':''}`} id="workspace-sidebar" aria-label="Рабочее пространство">
      <div className="sidebar-brand-row"><button className="sidebar-brand" onClick={()=>{onNavigate('documents');onClose();}} aria-label="B2B AntiRisk — документы"><span className="sidebar-brand-mark"><ShieldCheck size={21} strokeWidth={1.6}/></span><strong>B2B AntiRisk</strong></button><button className="sidebar-close" onClick={onClose} aria-label="Закрыть меню"><X size={19}/></button></div>
      <div className="sidebar-workspace-label"><span className="workspace-online-dot"/>ЛИЧНОЕ ПРОСТРАНСТВО</div>
      <button className="sidebar-create" onClick={()=>{onCreate();onClose();}}><Plus size={16}/><span>Новый проект</span><kbd>+</kbd></button>
      <nav className="sidebar-navigation" aria-label="Основная навигация">{items.map(item=>{
        const active=view===item.view || ((view==='project' || view==='document') && item.view==='documents');
        return <button key={item.view} className={active?'active':''} aria-current={active?'page':undefined} onClick={()=>{onNavigate(item.view);onClose();}}><item.Icon size={16} strokeWidth={1.5}/><span>{item.label}</span>{item.count!==null && <small>{item.count}</small>}</button>;
      })}</nav>
      <div className="sidebar-bottom"><button className="sidebar-help" onClick={()=>{onHelp();onClose();}}><CircleHelp size={16}/><span>Помощь и информация</span><ChevronRight size={13}/></button><div className="sidebar-user"><span className="sidebar-avatar">{user?.initials || '…'}</span><span><strong>{user?.fullName || 'Загрузка профиля…'}</strong><small>{user?.email || 'Подключение к серверу'}</small></span></div></div>
    </aside>
  </>;
}
