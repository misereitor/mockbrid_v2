# Plugin do Figma — Mockbird Import

Reconstrói um projeto exportado do Mockbird como **frames com camadas editáveis**
(retângulos, textos e imagens) no Figma.

## Como exportar no Mockbird

1. Abra o projeto no editor.
2. Clique em **Figma/Penpot** na barra superior.
3. O navegador baixa `<projeto>.mockbird.json` com a geometria de cada tela.

## Como instalar o plugin (modo desenvolvimento)

1. Abra o Figma **desktop** (plugins de desenvolvimento não rodam no Figma web).
2. Menu → **Plugins → Development → Import plugin from manifest…**
3. Selecione `integrations/figma-plugin/manifest.json`.
4. Rode **Plugins → Development → Mockbird Import**, escolha (ou arraste) o `.mockbird.json`
   e clique em **Importar para o Figma**.

Cada tela vira um frame de 1440×900 (ou o tamanho real da tela) lado a lado.
Imagens externas são baixadas pelo plugin; quando o download falha, a camada vira um
retângulo cinza translúcido para não sumir do layout.

## Limitações conhecidas

- Sombras, gradientes complexos, `clip-path` e máscaras não são reproduzidos (gradiente
  vira a primeira cor sólida).
- O texto é recriado com a família/peso/tamanho e a largura medidas no navegador; a
  quebra de linha pode diferir se a fonte não existir no Figma (fallback para Inter).
- O plugin importa para a página atual do arquivo, começando em `(0, 0)`.
