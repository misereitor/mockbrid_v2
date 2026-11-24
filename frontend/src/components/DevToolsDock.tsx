import { useEffect, useState } from 'react';

type NodeItem = { id: string; tag: string; attributes: Record<string, string>; textSnippet: string; parentId: string | null; childIds: string[]; rect: { width: number; height: number } };
type ConsoleItem = { level: string; text: string };
type NetworkItem = { method: string; url: string; status: number; duration: number; ok: boolean; error?: string };

const message = (payload: Record<string, unknown>) => document.querySelector<HTMLIFrameElement>('iframe[data-mockbird-canvas="frame"]')?.contentWindow?.postMessage(payload, '*');

export function DevToolsDock() {
  const [tab, setTab] = useState('elements');
  const [nodes, setNodes] = useState<NodeItem[]>([]);
  const [consoleItems, setConsoleItems] = useState<ConsoleItem[]>([]);
  const [network, setNetwork] = useState<NetworkItem[]>([]);
  const [styles, setStyles] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [profile, setProfile] = useState('off');
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const data = event.data;
      if (!data) return;
      if (data.type === 'MOCKBIRD_DEVTOOLS_CONSOLE') setConsoleItems((items) => [...items, { level: data.level, text: data.text }].slice(-200));
      if (data.type === 'MOCKBIRD_DEVTOOLS_NETWORK') setNetwork((items) => [...items, data].slice(-200));
      if (data.type === 'MOCKBIRD_DEVTOOLS_DOM_TREE') {
        setNodes(data.nodes);
        if (!selected && data.nodes[0]) { setSelected(data.nodes[0].id); message({ type: 'MOCKBIRD_DEVTOOLS_REQUEST_STYLES', nodeId: data.nodes[0].id }); }
      }
      if (data.type === 'MOCKBIRD_ELEMENT_SELECTED' && data.devtoolsNodeId) { setSelected(data.devtoolsNodeId); message({ type: 'MOCKBIRD_DEVTOOLS_REQUEST_STYLES', nodeId: data.devtoolsNodeId }); }
      if (data.type === 'MOCKBIRD_DEVTOOLS_STYLES') setStyles(data.styles);
    };
    window.addEventListener('message', onMessage);
    const requestDom = () => message({ type: 'MOCKBIRD_DEVTOOLS_REQUEST_DOM' });
    const frame = document.querySelector<HTMLIFrameElement>('iframe[data-mockbird-canvas="frame"]');
    frame?.addEventListener('load', requestDom);
    requestDom();
    const timer = window.setInterval(requestDom, 500);
    return () => { window.removeEventListener('message', onMessage); frame?.removeEventListener('load', requestDom); window.clearInterval(timer); };
  }, []);
  const pick = (id: string) => { setSelected(id); message({ type: 'MOCKBIRD_DEVTOOLS_SELECT_NODE', nodeId: id }); message({ type: 'MOCKBIRD_DEVTOOLS_REQUEST_STYLES', nodeId: id }); };
  const throttle = (value: string) => { setProfile(value); message({ type: 'MOCKBIRD_DEVTOOLS_SET_THROTTLE', profile: value }); };
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  return <section data-testid="devtools-dock" className="shrink-0 h-56 border-t border-mockbird-border bg-mockbird-surface text-xs overflow-hidden">
    <nav className="h-9 flex items-center gap-1 px-2 border-b border-mockbird-border">
      {(['elements', 'console', 'network', 'styles'] as const).map((name) => <button key={name} data-testid={`devtools-tab-${name}`} onClick={() => setTab(name)} className={`px-2 py-1 rounded ${tab === name ? 'bg-mockbird-card text-mockbird-cyan' : 'text-[var(--ui-muted)]'}`}>{name === 'elements' ? 'Elementos' : name === 'console' ? 'Console' : name === 'network' ? 'Rede' : 'Estilos'}</button>)}
      <select data-testid="network-type" value={profile} onChange={(event) => throttle(event.target.value)} className="ml-auto bg-mockbird-card px-1 py-1"><option value="off">Sem rede</option><option value="slow3g">Slow 3G</option><option value="4g">4G</option></select>
    </nav>
    <div className="p-2 h-[calc(100%-2.25rem)] overflow-auto">
      {tab === 'elements' && <div>{nodes.map((node) => <button key={node.id} onClick={() => pick(node.id)} className={`block text-left pl-2 py-0.5 ${selected === node.id ? 'text-mockbird-cyan' : ''}`} style={{ paddingLeft: `${Math.min((node.parentId ? 1 : 0) * 12, 24)}px` }}>&lt;{node.tag}&gt; {node.textSnippet}</button>)}</div>}
      {tab === 'console' && <div>{consoleItems.map((item, index) => <div key={index}><b className="mr-2">{item.level}</b>{item.text}</div>)}</div>}
      {tab === 'network' && <div>{network.map((item, index) => <div key={index} className="flex gap-2"><b>{item.method}</b><span className="truncate">{item.url}</span><span>{item.status}</span><span>{item.duration}ms</span><span>{item.ok ? 'ok' : 'erro'}</span></div>)}</div>}
      {tab === 'styles' && (Object.keys(styles).length ? <div>{Object.entries(styles).map(([key, value]) => <div key={key}><b>{key}</b>: {value}</div>)}</div> : <div className="text-[var(--ui-muted)]">Selecione um elemento no canvas</div>)}
      {tab === 'elements' && selected && <span className="hidden">{nodeMap.get(selected)?.tag}</span>}
    </div>
  </section>;
}
