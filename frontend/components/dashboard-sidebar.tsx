'use client';

import { BookOpenCheck, ChevronRight, CircleHelp, Layers3, Plus, Settings2, X } from 'lucide-react';
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
  keepNavigationOpen?: boolean;
}

export function DashboardSidebar({view,user,projectCount,ruleCount,open,onClose,onNavigate,onCreate,onHelp,keepNavigationOpen=false}: Props) {
  const items = [
    {view:'documents' as const,label:'Проекты',Icon:Layers3,count:projectCount},
    {view:'rules' as const,label:'Правила проверки',Icon:BookOpenCheck,count:ruleCount},
    {view:'settings' as const,label:'Настройки',Icon:Settings2,count:null},
  ];
  return <>
    {open && <button className="dashboard-scrim" aria-label="Закрыть меню" onClick={onClose} />}
    <aside className={`dashboard-sidebar ${open?'is-open':''}`} id="workspace-sidebar" aria-label="Рабочее пространство">
      <div className="sidebar-brand-row"><button className="sidebar-brand" onClick={()=>{onNavigate('documents');onClose();}} aria-label="AntiRisk — проекты"><span className="sidebar-brand-mark" aria-hidden="true"><img src="/antirisk-logo.svg" alt="" /></span><strong>AntiRisk</strong></button><button className="sidebar-close" onClick={onClose} aria-label="Закрыть меню"><X size={19}/></button></div>
      <button className="sidebar-create" data-onboarding="new-project" onClick={()=>{onCreate();onClose();}}><span className="sidebar-create-icon" aria-hidden="true"><Plus size={18}/></span><span>Новый проект</span></button>
      <nav className="sidebar-navigation" aria-label="Основная навигация">{items.map(item=>{
        const active=view===item.view || ((view==='project' || view==='document') && item.view==='documents');
        return <button key={item.view} data-onboarding={`nav-${item.view}`} className={active?'active':''} aria-current={active?'page':undefined} onClick={()=>{onNavigate(item.view);if(!keepNavigationOpen)onClose();}}><item.Icon size={16} strokeWidth={1.5}/><span>{item.label}</span>{item.count!==null && <small>{item.count}</small>}</button>;
      })}</nav>
      <div className="sidebar-bottom"><button className="sidebar-help" onClick={()=>{onHelp();onClose();}}><CircleHelp size={17}/><span>Помощь и информация</span><ChevronRight size={14}/></button><button type="button" className="sidebar-user" aria-label="Открыть настройки профиля" onClick={()=>{onNavigate('settings');onClose();}}><span className="sidebar-avatar">{user?.initials || '…'}</span><span><strong title={user?.fullName}>{user?.fullName || 'Загрузка профиля…'}</strong></span><ChevronRight size={14} aria-hidden="true" /></button></div>
    </aside>
  </>;
}
