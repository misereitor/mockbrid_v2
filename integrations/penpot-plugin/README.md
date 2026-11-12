# Plugin do Penpot — Mockbird Import

Reconstrói um projeto exportado do Mockbird como **boards editáveis** (retângulos,
textos e imagens) no Penpot.

## Como exportar no Mockbird

1. Abra o projeto no editor.
2. Clique em **Figma/Penpot** na barra superior.
3. O navegador baixa `<projeto>.mockbird.json`.

## Como instalar

O Penpot não tem "importar pasta": o plugin precisa ser servido por HTTP.

```bash
cd integrations/penpot-plugin
python3 -m http.server 8787
```

Depois, no Penpot:

1. Abra um projeto e aperte `Ctrl+Alt+P` (plugin manager).
2. Cole `http://localhost:8787/manifest.json` e instale.
3. Rode **Mockbird Import**, escolha o `.mockbird.json` e clique em **Importar**.

A interface vai embutida no `plugin.js` (data URI), então não há dependência de
host para o seletor de arquivo.

## Limitações conhecidas

- Sombras, gradientes complexos, `clip-path` e máscaras não são reproduzidos
  (gradiente vira a primeira cor sólida).
- Fontes ausentes no Penpot caem para a fonte padrão do arquivo.
- Imagens externas são baixadas pelo `penpot.uploadMediaUrl`; se o download falhar a
  camada vira um retângulo cinza translúcido.
- Os boards são criados na página ativa a partir de `(0, 0)`.
