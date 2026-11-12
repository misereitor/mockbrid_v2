# Bundle de design (`mockbird.design-bundle/v1`)

Formato JSON que leva um projeto do Mockbird para o **Figma**, o **Penpot** ou o
**navegador** como camadas editáveis.

Ao contrário do ZIP `design/` (que preserva o corpus HTML do v1), o bundle
descreve a **geometria renderizada**: cada tela é medida no navegador e vira uma
lista plana de camadas com coordenadas absolutas.

## Como gerar

No editor do projeto, clique em **Figma/Penpot** na barra superior. O app:

1. busca os tokens do projeto;
2. renderiza cada tela salva num iframe oculto (mesmo documento do canvas, com
   Tailwind e as variáveis de token);
3. percorre o DOM medindo fundos, bordas, textos (`Range` por nó de texto) e
   imagens;
4. baixa `<projeto>.mockbird.json`.

A extensão de navegador gera o mesmo formato com uma tela só, a partir da página
aberta.

## Estrutura

```jsonc
{
  "format": "mockbird.design-bundle",
  "version": 1,
  "exported_at": "2026-11-11T12:00:00.000Z",
  "project": { "id": "…", "name": "Portal do cliente", "slug": "portal" },
  "tokens": { "light": { "color-primary": "#0f766e" }, "dark": {}, "shared": {} },
  "screens": [
    {
      "id": "…",
      "name": "Login",
      "width": 1440,
      "height": 900,
      "device_type": "desktop",
      "is_entry": true,
      "background": "#0b1120",
      "html": "<div class=\"…\">…</div>",
      "css": "",
      "layers": []
    }
  ],
  "warnings": ["Tela X exportada sem camadas: …"]
}
```

### Camada

Todas as coordenadas são absolutas em relação ao canto superior esquerdo da tela.

| Campo | Tipo | Observação |
| :--- | :--- | :--- |
| `type` | `rect`, `text` ou `image` | define como o plugin cria a forma |
| `name` | string | tag/id/classe usados no HTML |
| `x`, `y`, `width`, `height` | number | px, já arredondados |
| `fill`, `fillOpacity` | hex, 0–1 | preenchimento de `rect` |
| `radius` | number | raio do canto superior esquerdo |
| `border` | `{ color, width }` | borda sólida |
| `color` | hex | cor do texto |
| `fontSize`, `fontWeight`, `fontFamily` | number/string | estilo do texto |
| `lineHeight` | number | px; `0` = automático |
| `letterSpacing` | number | px |
| `align` | `left`/`center`/`right`/`justify` | alinhamento horizontal |
| `text` | string | conteúdo (até 2.000 caracteres) |
| `src` | string | URL ou data URI (imagens e `svg` serializado) |
| `opacity` | number | opacidade herdada do elemento |

As camadas vêm na ordem do DOM: pais antes dos filhos, fundos antes dos textos.

## O que os plugins fazem

- **Figma** (`integrations/figma-plugin`): cria um frame por tela, com clipping e
  fundo, e recria retângulos/textos/imagens nas coordenadas do bundle. Fontes são
  carregadas com fallback para Inter; imagens são baixadas via `figma.createImage`.
- **Penpot** (`integrations/penpot-plugin`): cria um board por tela e recria as
  camadas com `createRectangle`, `createText` e `uploadMediaUrl`.
- **Extensão** (`integrations/browser-extension`): captura a página ativa e gera um
  bundle de uma tela.

Os três aceitam o mesmo arquivo. Também é possível colar o JSON na interface dos
plugins.

## Limitações conhecidas

- O bundle carrega a **geometria medida**, não CSS executável: layout responsivo
  vira posicionamento absoluto.
- Sombras, gradientes, filtros, `clip-path` e máscaras não são reproduzidos;
  gradientes caem para a primeira cor sólida.
- Textos são posicionados pela caixa medida no navegador — se a fonte não existir
  no destino, a quebra de linha pode mudar.
- O HTML/CSS vem do **estado atual do editor** (edições não salvas entram); os tokens vêm do servidor.
- Conteúdo dentro de `iframe`, `canvas` ou vídeo não é capturado.
- O limite é de 60 telas por exportação e 4.000 camadas por captura da extensão.
