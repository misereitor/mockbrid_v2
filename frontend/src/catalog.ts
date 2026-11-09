export interface ComponentTemplate {
  id: string;
  name: string;
  category: 'Actions' | 'Layout' | 'Feedback' | 'Typography' | 'Forms' | 'Navigation' | 'SaaS';
  defaultHtml: string;
  description: string;
}

export const BASE_COMPONENTS: ComponentTemplate[] = [
  {
    id: 'hero-saas',
    name: 'Hero Banner SaaS',
    category: 'SaaS',
    description: 'Header principal com título impactante, badge e dois botões de CTA',
    defaultHtml: `<div class="py-12 px-6 rounded-2xl bg-gradient-to-r from-[var(--color-surface)] to-[var(--color-bg)] border border-[var(--color-border)] text-center space-y-4" data-mb-id="hero-saas">
  <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-blue-500/10 text-[var(--color-primary)] border border-blue-500/20">
    🚀 Nova Versão 2.0 Disponível
  </div>
  <h1 class="text-3xl sm:text-4xl font-extrabold text-[var(--color-text)] tracking-tight">
    Construa seu SaaS com Design System e Velocidade
  </h1>
  <p class="max-w-xl mx-auto text-sm opacity-80 text-[var(--color-text)]">
    Valide suas ideias com protótipos reais e design tokens antes de escrever uma única linha de backend.
  </p>
  <div class="flex items-center justify-center gap-3 pt-2">
    <button class="px-5 py-2.5 rounded-lg bg-[var(--color-primary)] text-white text-xs font-semibold shadow-md" data-toast="Iniciando teste grátis!">
      Começar Agora
    </button>
    <button class="px-5 py-2.5 rounded-lg border border-[var(--color-border)] text-[var(--color-text)] text-xs font-semibold hover:bg-[var(--color-surface)]">
      Ver Demonstração
    </button>
  </div>
</div>`
  },
  {
    id: 'kpi-metric-card',
    name: 'Card de Métrica / KPI',
    category: 'SaaS',
    description: 'Indicador de MRR, faturamento ou clientes com percentual de crescimento',
    defaultHtml: `<div class="p-5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] space-y-2" data-mb-id="kpi-metric">
  <div class="flex items-center justify-between text-xs opacity-75 text-[var(--color-text)] font-medium">
    <span>Receita Mensal Recorrente (MRR)</span>
    <span class="text-emerald-400 font-bold bg-emerald-500/10 px-2 py-0.5 rounded-full text-[10px]">+18.4%</span>
  </div>
  <div class="text-2xl font-extrabold text-[var(--color-text)]">
    R$ 48.750,00
  </div>
  <p class="text-[11px] opacity-60 text-[var(--color-text)]">
    Comparado aos últimos 30 dias de faturamento.
  </p>
</div>`
  },
  {
    id: 'data-table-saas',
    name: 'Tabela de Dados SaaS',
    category: 'SaaS',
    description: 'Tabela responsiva com cabeçalhos, status e ações rápidas',
    defaultHtml: `<div class="w-full overflow-x-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]" data-mb-id="table-saas">
  <table class="w-full text-left text-xs text-[var(--color-text)]">
    <thead class="border-b border-[var(--color-border)] opacity-70 uppercase tracking-wider text-[10px] bg-[var(--color-bg)]/40">
      <tr>
        <th class="py-3 px-4">Cliente / Empresa</th>
        <th class="py-3 px-4">Plano</th>
        <th class="py-3 px-4">Status</th>
        <th class="py-3 px-4">Ação</th>
      </tr>
    </thead>
    <tbody class="divide-y divide-[var(--color-border)]">
      <tr>
        <td class="py-3 px-4 font-semibold">Acme Tech Soluções</td>
        <td class="py-3 px-4">Enterprise</td>
        <td class="py-3 px-4"><span class="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 text-[10px] font-bold">Ativo</span></td>
        <td class="py-3 px-4"><button class="text-[var(--color-primary)] hover:underline font-semibold" data-toast="Editando cliente Acme">Editar</button></td>
      </tr>
      <tr>
        <td class="py-3 px-4 font-semibold">Nexus Softwares</td>
        <td class="py-3 px-4">Pro Mensal</td>
        <td class="py-3 px-4"><span class="px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-400 text-[10px] font-bold">Trial</span></td>
        <td class="py-3 px-4"><button class="text-[var(--color-primary)] hover:underline font-semibold" data-toast="Editando cliente Nexus">Editar</button></td>
      </tr>
    </tbody>
  </table>
</div>`
  },
  {
    id: 'pricing-card',
    name: 'Card de Plano / Pricing',
    category: 'SaaS',
    description: 'Card de pricing com lista de benefícios e botão de assinatura',
    defaultHtml: `<div class="p-6 rounded-2xl border-2 border-[var(--color-primary)] bg-[var(--color-surface)] shadow-xl space-y-4 max-w-sm" data-mb-id="pricing-card">
  <div class="flex items-center justify-between">
    <h3 class="font-bold text-base text-[var(--color-text)]">Plano Pro SaaS</h3>
    <span class="px-2 py-0.5 rounded-full bg-[var(--color-primary)] text-white text-[10px] font-bold uppercase">Popular</span>
  </div>
  <div class="flex items-baseline gap-1">
    <span class="text-3xl font-extrabold text-[var(--color-text)]">R$ 149</span>
    <span class="text-xs opacity-70 text-[var(--color-text)]">/mês</span>
  </div>
  <ul class="text-xs space-y-2 opacity-90 text-[var(--color-text)] pt-2 border-t border-[var(--color-border)]">
    <li class="flex items-center gap-2">✓ Usuários ilimitados</li>
    <li class="flex items-center gap-2">✓ Suporte a Modelos Customizados de IA</li>
    <li class="flex items-center gap-2">✓ Servidor MCP Nativo incluído</li>
  </ul>
  <button class="w-full py-2.5 rounded-lg bg-[var(--color-primary)] text-white text-xs font-semibold shadow-md" data-toast="Plano selecionado com sucesso!">
    Assinar Plano Pro
  </button>
</div>`
  },
  {
    id: 'btn-primary',
    name: 'Button (Primário)',
    category: 'Actions',
    description: 'Botão de ação principal com cor de destaque do tema',
    defaultHtml: `<button class="px-5 py-2.5 rounded-lg bg-[var(--color-primary)] text-white font-medium text-sm shadow-md hover:opacity-90 transition active:scale-95 flex items-center justify-center gap-2" data-mb-id="btn-primary" data-toast="Ação Executada!">
  <span>Ação Principal</span>
</button>`
  },
  {
    id: 'btn-secondary',
    name: 'Button (Secundário / Outline)',
    category: 'Actions',
    description: 'Botão com borda fina e fundo transparente',
    defaultHtml: `<button class="px-5 py-2.5 rounded-lg border border-[var(--color-border)] text-[var(--color-text)] font-medium text-sm hover:bg-[var(--color-surface)] transition active:scale-95" data-mb-id="btn-secondary">
  Cancelar
</button>`
  },
  {
    id: 'card-surface',
    name: 'Card de Conteúdo',
    category: 'Layout',
    description: 'Container estruturado com borda suave e fundo de superfície',
    defaultHtml: `<div class="p-6 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] shadow-sm space-y-3" data-mb-id="card-sample">
  <h3 class="text-lg font-bold text-[var(--color-text)]" data-mb-id="card-title">Título do Card</h3>
  <p class="text-sm opacity-75 text-[var(--color-text)]" data-mb-id="card-desc">Este é um exemplo de card responsivo estilizado com variáveis do Design System.</p>
</div>`
  },
  {
    id: 'input-field',
    name: 'Field / Input de Formulário',
    category: 'Forms',
    description: 'Input com label acessível e foco inteligente',
    defaultHtml: `<div class="space-y-1.5 w-full" data-mb-id="field-group">
  <label class="block text-xs font-semibold text-[var(--color-text)] opacity-90" data-mb-id="field-label">Endereço de E-mail</label>
  <input type="email" placeholder="usuario@empresa.com" class="w-full px-4 py-2.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]" data-mb-id="field-input" />
</div>`
  },
  {
    id: 'modal-dialog',
    name: 'Modal Dialog (Overlay)',
    category: 'Feedback',
    description: 'Modal centrado sobreposto com ação de fechamento',
    defaultHtml: `<div class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50" data-mb-id="modal-overlay">
  <div class="w-full max-w-md bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl p-6 shadow-2xl space-y-4" data-mb-id="modal-box">
    <div class="flex items-center justify-between" data-mb-id="modal-header">
      <h3 class="font-bold text-lg text-[var(--color-text)]">Confirmar Ação</h3>
      <button class="text-sm opacity-50 hover:opacity-100 p-1" data-close>&times;</button>
    </div>
    <p class="text-sm opacity-80 text-[var(--color-text)]">Tem certeza que deseja aplicar esta alteração no protótipo?</p>
    <div class="flex justify-end gap-2 pt-2">
      <button class="px-4 py-2 text-xs font-medium rounded-lg border border-[var(--color-border)] text-[var(--color-text)]" data-close>Cancelar</button>
      <button class="px-4 py-2 text-xs font-medium rounded-lg bg-[var(--color-primary)] text-white" data-toast="Confirmado!">Confirmar</button>
    </div>
  </div>
</div>`
  },
  {
    id: 'tabs-navigation',
    name: 'Tabs (Abas de Navegação)',
    category: 'Navigation',
    description: 'Navegação por abas com estado ativo',
    defaultHtml: `<div class="w-full space-y-3" data-mb-id="tabs-container">
  <div class="flex border-b border-[var(--color-border)] gap-4 text-xs font-semibold">
    <button class="pb-2 border-b-2 border-[var(--color-primary)] text-[var(--color-primary)]">Visão Geral</button>
    <button class="pb-2 border-b-2 border-transparent text-[var(--color-text)] opacity-60 hover:opacity-100">Métricas</button>
    <button class="pb-2 border-b-2 border-transparent text-[var(--color-text)] opacity-60 hover:opacity-100">Histórico</button>
  </div>
</div>`
  }
];
