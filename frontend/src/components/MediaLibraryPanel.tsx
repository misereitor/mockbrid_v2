import React, { useEffect, useState, useRef } from 'react';
import { 
  Image as ImageIcon, 
  Upload, 
  Trash2, 
  Copy, 
  Check, 
  AlertTriangle, 
  RefreshCw, 
  Search
} from 'lucide-react';
import { 
  ProjectAsset, 
  listProjectAssets, 
  uploadProjectAsset, 
  deleteProjectAsset, 
  getBrokenImages, 
  replaceAssetUrls, 
  imageHtml, 
  formatBytes 
} from '../lib/assets';

interface MediaLibraryPanelProps {
  projectId: string;
  onInsertImage?: (html: string) => void;
  onNotify?: (msg: string) => void;
  onRefreshScreens?: () => void;
}

export const MediaLibraryPanel: React.FC<MediaLibraryPanelProps> = ({
  projectId,
  onInsertImage,
  onNotify,
  onRefreshScreens,
}) => {
  const [assets, setAssets] = useState<ProjectAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [brokenUrls, setBrokenUrls] = useState<string[]>([]);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [selectedReplacementAsset, setSelectedReplacementAsset] = useState<Record<string, string>>({});
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadData = async () => {
    setLoading(true);
    try {
      const [list, broken] = await Promise.all([
        listProjectAssets(projectId),
        getBrokenImages(projectId),
      ]);
      setAssets(list);
      setBrokenUrls(broken);
    } catch (err: any) {
      console.error('Erro ao carregar mídia:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [projectId]);

  const handleFileUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    let successCount = 0;
    try {
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const created = await uploadProjectAsset(projectId, file);
        setAssets((prev) => [created, ...prev]);
        successCount++;
      }
      onNotify?.(`${successCount} arquivo(s) enviado(s) com sucesso.`);
      // Atualiza lista de caminhos quebrados
      const broken = await getBrokenImages(projectId);
      setBrokenUrls(broken);
    } catch (err: any) {
      alert(err.message || 'Erro ao enviar asset');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDelete = async (asset: ProjectAsset) => {
    if (!window.confirm(`Tem certeza que deseja excluir "${asset.original_name}"?`)) return;
    try {
      await deleteProjectAsset(projectId, asset.id);
      setAssets((prev) => prev.filter((a) => a.id !== asset.id));
      onNotify?.('Asset excluído.');
    } catch (err: any) {
      alert(err.message || 'Erro ao excluir asset');
    }
  };

  const handleCopyUrl = (asset: ProjectAsset) => {
    const fullUrl = asset.url.startsWith('http') ? asset.url : `${window.location.origin}${asset.url}`;
    navigator.clipboard.writeText(fullUrl);
    setCopiedId(asset.id);
    setTimeout(() => setCopiedId(null), 2000);
    onNotify?.('URL assinada copiada para a área de transferência.');
  };

  const handleReplaceBrokenUrl = async (oldUrl: string) => {
    const assetId = selectedReplacementAsset[oldUrl] || (assets[0] ? assets[0].id : '');
    if (!assetId) {
      alert('Selecione uma imagem para substituir o caminho quebrado.');
      return;
    }
    try {
      const res = await replaceAssetUrls(projectId, oldUrl, assetId);
      onNotify?.(res.message || `Substituído com sucesso em ${res.replaced_screens} tela(s)!`);
      const broken = await getBrokenImages(projectId);
      setBrokenUrls(broken);
      onRefreshScreens?.();
    } catch (err: any) {
      alert(err.message || 'Erro ao substituir asset');
    }
  };

  const filteredAssets = assets.filter((a) =>
    a.original_name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="flex flex-col h-full bg-mockbird-surface text-slate-200 select-none overflow-hidden">
      {/* Cabeçalho */}
      <div className="h-11 px-3 border-b border-mockbird-border flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <ImageIcon size={15} className="text-mockbird-cyan" />
          <span className="text-xs font-semibold text-white">Mídia & Logos</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-mockbird-card text-slate-400 font-mono">
            {assets.length}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={loadData}
            disabled={loading}
            className="p-1 rounded text-slate-400 hover:text-white hover:bg-white/5 transition"
            title="Recarregar"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1 px-2.5 py-1 rounded bg-mockbird-blue hover:bg-mockbird-bluedark text-white text-[11px] font-semibold transition"
            title="Enviar imagem (PNG, JPG, SVG, WebP, GIF)"
          >
            <Upload size={12} />
            <span>{uploading ? 'Enviando…' : 'Upload'}</span>
          </button>
        </div>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
        className="hidden"
        onChange={(e) => handleFileUpload(e.target.files)}
      />

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* Banner de Imagens Quebradas / Relink Automático */}
        {brokenUrls.length > 0 && (
          <div className="p-2.5 rounded-lg bg-amber-950/30 border border-amber-500/40 text-xs space-y-2">
            <div className="flex items-center gap-1.5 font-semibold text-amber-300">
              <AlertTriangle size={14} className="text-amber-400 shrink-0" />
              <span>{brokenUrls.length} imagem(ns) quebrada(s) detectada(s)</span>
            </div>
            <p className="text-[11px] text-slate-300 leading-relaxed">
              Caminhos relativos locais das telas importadas podem ser vinculados a imagens da biblioteca:
            </p>
            <div className="space-y-1.5 pt-1">
              {brokenUrls.map((oldUrl) => (
                <div key={oldUrl} className="flex flex-col gap-1 p-1.5 rounded bg-black/40 border border-white/5">
                  <span className="font-mono text-[10px] text-rose-300 truncate" title={oldUrl}>
                    {oldUrl}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <select
                      value={selectedReplacementAsset[oldUrl] || ''}
                      onChange={(e) =>
                        setSelectedReplacementAsset((prev) => ({ ...prev, [oldUrl]: e.target.value }))
                      }
                      className="flex-1 bg-mockbird-bg border border-mockbird-border text-slate-200 px-1.5 py-1 rounded text-[10px] outline-none"
                    >
                      <option value="">Selecione uma imagem...</option>
                      {assets.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.original_name}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => handleReplaceBrokenUrl(oldUrl)}
                      className="px-2 py-1 rounded bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 border border-amber-500/40 text-[10px] font-semibold whitespace-nowrap transition"
                    >
                      Substituir
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Campo de Busca */}
        {assets.length > 4 && (
          <div className="flex items-center gap-1.5 bg-mockbird-bg border border-mockbird-border px-2.5 py-1 rounded-md text-xs">
            <Search size={12} className="text-slate-500" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar por nome..."
              className="bg-transparent outline-none w-full text-slate-200 text-[11px]"
            />
          </div>
        )}

        {/* Dropzone visual */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            handleFileUpload(e.dataTransfer.files);
          }}
          onClick={() => fileInputRef.current?.click()}
          className="border-2 border-dashed border-mockbird-border hover:border-mockbird-cyan/60 rounded-xl p-4 text-center cursor-pointer transition hover:bg-mockbird-card/30 flex flex-col items-center justify-center gap-1"
        >
          <Upload size={18} className="text-slate-500" />
          <span className="text-[11px] font-medium text-slate-300">
            Arraste imagens ou clique para fazer upload
          </span>
          <span className="text-[10px] text-slate-500">
            PNG, JPG, SVG, WebP ou GIF até 15 MB
          </span>
        </div>

        {/* Lista de Imagens */}
        {filteredAssets.length === 0 && !loading && (
          <div className="text-center py-8 text-xs text-slate-500">
            Nenhuma imagem encontrada.
          </div>
        )}

        <div className="grid grid-cols-2 gap-2">
          {filteredAssets.map((asset) => (
            <div
              key={asset.id}
              className="group relative flex flex-col rounded-lg bg-mockbird-card border border-mockbird-border overflow-hidden hover:border-mockbird-cyan/50 transition"
            >
              {/* Preview Thumbnail */}
              <div className="h-24 w-full bg-[#12171b] flex items-center justify-center p-2 overflow-hidden relative">
                <img
                  src={asset.url}
                  alt={asset.original_name}
                  className="max-h-full max-w-full object-contain"
                  loading="lazy"
                />
                <span className="absolute bottom-1 right-1 px-1 py-0.5 rounded bg-black/70 text-[9px] font-mono text-slate-400">
                  {formatBytes(asset.size_bytes)}
                </span>
              </div>

              {/* Info + Ações */}
              <div className="p-2 flex flex-col gap-1 text-[11px]">
                <span className="font-medium text-slate-200 truncate" title={asset.original_name}>
                  {asset.original_name}
                </span>

                <div className="flex items-center justify-between pt-1 gap-1">
                  <button
                    onClick={() => handleCopyUrl(asset)}
                    className="p-1 rounded text-slate-400 hover:text-white hover:bg-white/10 transition"
                    title="Copiar URL assinada"
                  >
                    {copiedId === asset.id ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                  </button>

                  {onInsertImage && (
                    <button
                      onClick={() => {
                        onInsertImage(imageHtml(asset));
                        onNotify?.(`"${asset.original_name}" inserida na tela.`);
                      }}
                      className="px-2 py-0.5 rounded bg-mockbird-blue/20 hover:bg-mockbird-blue text-mockbird-cyan hover:text-white text-[10px] font-semibold transition"
                      title="Inserir esta imagem no canvas"
                    >
                      Inserir
                    </button>
                  )}

                  <button
                    onClick={() => handleDelete(asset)}
                    className="p-1 rounded text-slate-500 hover:text-rose-400 hover:bg-rose-950/20 transition"
                    title="Excluir imagem"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
