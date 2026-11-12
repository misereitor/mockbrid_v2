# Extensão de navegador — Capturar página

Transforma **qualquer página web** em um bundle `mockbird.design-bundle/v1` com
camadas editáveis (retângulos, textos e imagens), pronto para importar no Figma
ou no Penpot.

## Instalar (Chrome/Edge, modo desenvolvedor)

1. Abra `chrome://extensions` e ative o **Modo do desenvolvedor**.
2. **Carregar sem compactação** → selecione `integrations/browser-extension`.
3. Abra a página que quer capturar e clique no ícone da extensão.
4. **Capturar página** → **Baixar .mockbird.json** (ou **Copiar JSON**).
5. Importe o arquivo no plugin do [Figma](../figma-plugin/README.md) ou do
   [Penpot](../penpot-plugin/README.md).

## O que é capturado

- Dimensões: largura da viewport e altura total da página (inclui rolagem).
- Camadas: todo elemento com fundo/borda vira retângulo; cada nó de texto vira
  uma camada com fonte, peso, tamanho, cor e alinhamento; `img` e `svg` viram
  camadas de imagem.
- Limite de 4.000 camadas por captura para não travar a aba.

## Limitações conhecidas

- Páginas com `chrome://`, `about:`, Web Store ou PDFs internos não podem ser
  capturadas (restrição do navegador).
- Imagens protegidas por cookie/CORS podem falhar no download feito pelo plugin.
- Sombras, gradientes, `clip-path`, `position: sticky` e conteúdo em canvas/iframe
  não são reproduzidos fielmente.
- A extensão **não** envia nada para o servidor do Mockbird: ela só gera o arquivo
  local para o plugin importar.
