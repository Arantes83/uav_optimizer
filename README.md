# UAV Topology Optimizer

Addon para Blender focado em pós-processamento de malhas de fotogrametria e LiDAR.

O objetivo do projeto é transformar uma malha densa e difícil de usar em um asset mais limpo, leve e pronto para retopo, UV, packing, baking e geração de LODs, tudo dentro de um único painel em `View3D > Sidebar > UAV Opt`.

## Visão Geral

O addon organiza a pipeline em oito etapas:

1. Pre-processamento da malha
2. Simplificação por QEM
3. Retopologia em quads
4. Geração de seams em grade
5. UV unwrap nativo do Blender
6. Island Packing
7. Texture Baking
8. Geração de LODs

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
- rollback seguro quando a simplificação falha ou é pulada

### 3. Quad Retopology

- `QuadriFlow`
- `QuadWild`
- `Voxel Remesh`
- `Grid Projection` para terrenos com alinhamento em XY/Z

### 4. Grid Seams

- corte lógico em colunas e linhas
- marcação de seams sem separar o objeto

### 5. UV Unwrap

O módulo de UV usa apenas métodos nativos do Blender:

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

### 6. Island Packing

- engine nativa do Blender
- engine própria em Python com `Skyline` e `MaxRects`
- backend nativo em C++ para packing mais rápido
- busca iterativa e `simulated annealing`
- rotação configurável
- margin em UV ou pixels
- histórico de melhor ocupação por objeto e UV map
- build local do packer via `build_uvpack.bat`

### 7. Texture Baking

- bake de `Albedo`, `AO`, `Normal`, `Roughness`, `Metallic` e `Emission`
- modo `PBR` para gerar um conjunto completo de mapas em uma única execução
- saída em PNG
- controle de resolução, samples, margem e cage extrusion
- criação automática dos `Image Texture` nodes e conexão correta no material final

### 8. LOD Generation

- geração de múltiplos níveis de detalhe a partir do objeto ativo
- preview da tabela de LODs antes de gerar
- `LOD0` criado como cópia real do source
- decimate progressivo preservando seams UV
- coleção dedicada para agrupar `LOD0..LODn`
- objeto source preservado sem renomear nem sobrescrever a malha original

## Dependências Nativas

- `quadwild_lib`: integração externa usada no fluxo de retopologia
- `uvpack_lib`: wrapper `ctypes` para o packer UV em C++
- `uvpack_cpp`: código-fonte do backend nativo de packing

## Requisitos

- Blender `4.2+`
- Windows recomendado para o fluxo com `QuadWild` e para recompilar a DLL de packing

## Instalação

### Opção 1: instalar pelo ZIP

1. Gere um ZIP contendo a pasta do addon.
2. No Blender, vá em `Edit > Preferences > Add-ons`.
3. Clique em `Install...`.
4. Selecione o ZIP.
5. Ative `UAV Topology Optimizer`.

### Opção 2: instalar em modo de desenvolvimento

1. Copie a pasta do addon para a pasta de addons do Blender.
2. Reinicie o Blender ou use `Refresh`.
3. Ative `UAV Topology Optimizer` na lista de addons.

## Como Usar

Fluxo sugerido para terrenos e fotogrametria:

1. Rode `Mesh Pre-Processing` para limpar a malha bruta.
2. Use `QEM Simplification` para reduzir custo geométrico.
3. Gere uma nova malha com `QuadriFlow`, `QuadWild`, `Voxel` ou `Grid Projection`.
4. Crie seams com `Generate UV Grid Seams` se necessário.
5. Faça o unwrap em `UV Unwrapping`.
6. Rode `Island Packing` e escolha a engine mais adequada para o caso.
7. Faça o bake em `Texture Baking`, incluindo o modo `PBR` quando precisar gerar o conjunto completo de mapas.
8. Gere os LODs finais em `LOD Generation`, se necessário.

## Estrutura do Projeto

Arquivos principais:

- `__init__.py`
- `properties.py`
- `ui.py`
- `op_preprocess.py`
- `op_qem.py`
- `op_quadriflow.py`
- `op_quadwild.py`
- `op_shrinkwrap.py`
- `op_voxel.py`
- `op_chunk.py`
- `op_uv.py`
- `op_packing.py`
- `op_bake.py`
- `op_lod.py`

Pastas auxiliares:

- `quadwild_lib/`
- `quadwild_util/`
- `uvpack_cpp/`
- `uvpack_lib/`
- `third_party/`

## Build do Packer C++

Para recompilar a DLL do packer UV no Windows:

```powershell
.\build_uvpack.bat
```

O script procura uma instalação compatível do Visual Studio 2022, compila `uvpack.cpp` e copia os artefatos finais para `uvpack_lib/`.

## Atualizações Recentes

### 10/04/2026

- registro do addon ficou resiliente a reload parcial e a falhas de propriedades de cena
- novo fluxo de LOD com painel próprio e `LOD0` criado a partir de cópia real do source
- `Island Packing` ganhou seleção de engine, backend nativo em C++ e melhor ocupação persistida por objeto e UV map
- `Texture Baking` foi refeito com suporte a `PBR` e religação automática dos mapas no Shader Editor
- `QEM Simplification` agora faz rollback seguro quando a operação não produz uma malha válida

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

O foco atual é consolidar a pipeline de UV/packing, amadurecer o fluxo de bake e preparar a próxima geração do packer heurístico nativo.