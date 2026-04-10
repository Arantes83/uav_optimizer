# UAV Topology Optimizer

Addon para Blender focado em pós-processamento de malhas de fotogrametria e LiDAR.

O objetivo do projeto é transformar uma malha densa e difícil de usar em um asset mais limpo, leve e pronto para UV, packing e baking, tudo dentro de um único painel no `View3D > Sidebar > UAV Opt`.

## Visão Geral

O addon organiza a pipeline em sete etapas:

1. Pre-processamento da malha
2. Simplificação por QEM
3. Retopologia em quads
4. Geração de seams em grade
5. UV unwrap nativo do Blender
6. Packing de ilhas UV
7. Bake de texturas

## Recursos

### 1. Mesh Pre-Processing

- merge de vértices próximos
- remoção de degenerados
- smoothing controlado
- correção de spikes

### 2. QEM Simplification

- `Fast Decimate` usando o modificador nativo do Blender
- `True QEM`
- `Edge Length`
- controle por densidade, ratio ou contagem alvo de vértices

### 3. Quad Retopology

- `QuadriFlow`
- `QuadWild`
- `Voxel Remesh`
- `Grid Projection` para terrenos com alinhamento em XY/Z

### 4. Grid Seams

- corte lógico em colunas e linhas
- marcação de seams sem separar o objeto

### 5. UV Unwrap

O módulo de UV atual foi simplificado para usar apenas métodos nativos do Blender:

- `Smart UV Project`
- `Angle Based`
- `Conformal`
- `Minimum Stretch`

Também inclui:

- equalização de texel density
- leitura de estatísticas de UV
- cobertura de atlas
- stretch médio
- densidade média, mínima e máxima
- checagem de flipped faces e UVs fora de `0-1`

### 6. UV Packing

- engine própria em Python com `Skyline` e `MaxRects`
- busca iterativa
- simulated annealing
- rotação configurável
- margin em UV ou pixels
- histórico de melhor ocupação

### 7. Texture Baking

- bake de `Albedo`
- bake de `AO`
- bake de `Normal`
- saída em PNG
- controle de resolução, samples, margem e cage extrusion

## Requisitos

- Blender `4.2+`
- Windows recomendado para o fluxo com `QuadWild`

## Instalação

### Opção 1: instalar pelo ZIP

1. Gere um ZIP contendo a pasta do addon.
2. No Blender, vá em `Edit > Preferences > Add-ons`.
3. Clique em `Install...`.
4. Selecione o ZIP.
5. Ative `UAV Topology Optimizer`.

### Opção 2: instalar em modo de desenvolvimento

1. Copie a pasta do addon para sua pasta de addons do Blender.
2. Reinicie o Blender ou use `Refresh`.
3. Ative `UAV Topology Optimizer` na lista de addons.

## Como Usar

Fluxo sugerido para terrenos e fotogrametria:

1. Rode `Mesh Pre-Processing` para limpar a malha bruta.
2. Use `QEM Simplification` para reduzir custo geométrico.
3. Gere uma nova malha com `QuadriFlow`, `QuadWild`, `Voxel` ou `Grid Projection`.
4. Crie seams com `Generate UV Grid Seams` se necessário.
5. Faça o unwrap em `UV Unwrapping`.
6. Rode `Island Packing`.
7. Faça o bake em `Texture Baking`.

## Estrutura do Projeto

Arquivos principais:

- [__init__.py](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/__init__.py)
- [properties.py](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/properties.py)
- [ui.py](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/ui.py)
- [op_preprocess.py](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/op_preprocess.py)
- [op_qem.py](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/op_qem.py)
- [op_quadriflow.py](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/op_quadriflow.py)
- [op_quadwild.py](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/op_quadwild.py)
- [op_shrinkwrap.py](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/op_shrinkwrap.py)
- [op_voxel.py](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/op_voxel.py)
- [op_chunk.py](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/op_chunk.py)
- [op_uv.py](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/op_uv.py)
- [op_packing.py](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/op_packing.py)
- [op_bake.py](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/op_bake.py)

Pastas auxiliares:

- [quadwild_lib](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/quadwild_lib)
- [quadwild_util](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/quadwild_util)
- [third_party](C:/Users/rodri/OneDrive/Documentos/CODEX/Blender_Addons/uav_opt/third_party)

## Observações

- O painel foi pensado para workflow técnico, não para asset authoring genérico.
- O packing atual roda de forma síncrona. Em meshes grandes, ele pode bloquear a UI do Blender durante a busca.
- O módulo de UV atual usa apenas operadores nativos do Blender para unwrap.
- O fluxo com `QuadWild` depende das bibliotecas presentes em `quadwild_lib`.

## Desenvolvimento

Para versionar o projeto:

```powershell
git add .
git commit -m "Describe your change"
git push
```

Para validar sintaxe rapidamente:

```powershell
python -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8')) for p in pathlib.Path('.').rglob('*.py')]"
```

## Status

Projeto em desenvolvimento ativo.

O foco atual é consolidar a pipeline de UV/packing e melhorar performance em operações pesadas.
