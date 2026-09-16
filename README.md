# Predição de Falhas em Motores Elétricos Industriais com Machine Learning

Trabalho de Conclusão de Curso — João Vitor Toledo Hass

Sistema que recebe medições de vibração coletadas em campo por um técnico,
classifica a condição do motor e explica o diagnóstico, cruzando a predição do
modelo com indicadores normativos da ISO 10816/20816.

**A decisão que organiza o projeto:** o modelo de aprendizado identifica o
**tipo** de falha; quem decide a **severidade** é a norma, por cálculo físico.
Não é escolha de estilo — é resultado medido, e a seção
[Resultados](#resultados) mostra por quê.

---

## Subir o sistema

```bash
cp .env.example .env
```

Edite o `.env` e defina `POSTGRES_PASSWORD` e `JWT_SECRET_KEY`. Gere a chave com:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

```bash
docker compose up -d --build
```

A interface fica em **http://localhost:8080**. Interface e API são servidas na
mesma origem pelo nginx — os cookies de autenticação são httpOnly e SameSite, e
seriam tratados como *third-party* (portanto descartados) se estivessem em
origens diferentes.

Crie o primeiro usuário — não há usuário padrão embutido na imagem, de propósito:

```bash
docker compose exec api python scripts/seed_admin.py --email voce@empresa.com --name "Seu Nome"
```

A senha é pedida no terminal (mínimo de 12 caracteres) e não aparece na tela.


Três serviços: `db` (PostgreSQL, sem porta exposta), `api` (FastAPI com a camada
de ML no mesmo processo) e `web` (nginx servindo a interface e fazendo proxy da
API). O entrypoint da API aplica as migrations e registra os modelos antes de
atender.

---

## O que o sistema faz

Para cada medição enviada, na mesma requisição:

1. **Tipo de falha** — rolamento, desalinhamento, desbalanceamento ou normal.
   Vem do ensemble Random Forest + XGBoost.
2. **Severidade** — HEALTHY / WARNING / FAILURE. Vem do **critério físico**:
   zonas A/B/C/D da ISO 10816 pela magnitude absoluta, e variação sobre a
   medição de referência do motor quando ela existe.
3. **Indicadores normativos** — velocidade RMS na banda ISO, componentes 1× e 2×
   da rotação, aceleração em alta frequência.
4. **Matriz de decisão** — cruza a predição do modelo com a assinatura física e
   sinaliza divergência entre as evidências. Divergência nunca é silenciosa,
   mesmo quando a severidade é HEALTHY.
5. **Alerta**, quando a política dispara. A regra que disparou fica gravada no
   alerta, junto de um retrato do diagnóstico no momento — o modelo pode ser
   retreinado depois, e o alerta guarda o que se sabia.

A severidade prevista pelo modelo continua sendo calculada e gravada como
`ml_severity`, mas **não alimenta alertas nem decisão**. Ficou como registro do
experimento preliminar.

### Interface

Oito telas: painel com fila de inspeção priorizada, árvore da planta, alertas,
coleta em campo, detalhe do motor, cadastro da estrutura, trilha de auditoria e
login.

Duas merecem nota:

- **Detalhe do motor** — evolução dos indicadores ao longo das coletas, e a
  **forma de onda** de cada medição: clicar num ponto do gráfico mostra o sinal
  bruto daquela coleta, com pico a pico, pico, RMS e fator de crista.
- **`/auditoria`** — leitura da trilha, filtrada por padrão nos eventos
  sensíveis. Somente leitura: não há endpoint que a altere ou apague.

O registro de modelos é exposto pela API (`GET /models`), com métricas nos dois
protocolos, limitações conhecidas, espécimes reservados e conferência de
integridade que recalcula o SHA-256 do artefato contra o hash gravado. Não tem
tela na v1.

### O laço fechado

Na página do motor, o técnico registra o que encontrou ao inspecionar a máquina,
vinculado à previsão que aquilo confirma ou refuta. Com isso o acerto passa a ser
medido contra a realidade, e não apenas contra a partição de teste do mesmo
dataset que treinou o modelo.

O endpoint `/inspections/field-accuracy` devolve o viés junto do número:
inspeciona-se o que o sistema apontou como problema, e quase nunca o que ele
classificou como saudável. Abaixo de 20 confirmações ele declara amostra
insuficiente em vez de exibir um percentual sem significado.

---

## Resultados

Protocolo **leave-one-specimen-out**, sobre 4.500 janelas de 1 s
(`ml/scripts/12_metricas_completas.py`):

| Alvo | Acurácia | Acurácia balanceada | Macro-F1 | MCC |
| :--- | ---: | ---: | ---: | ---: |
| **Tipo de falha** | **88,7 %** | **85,4 %** | **0,852** | **0,845** |
| Severidade por ML | 63,0 % | 51,7 % | 0,468 | 0,245 |

O par de coeficientes de Matthews é o que justifica a arquitetura. O MCC só é
alto quando **todas** as classes vão bem: 0,845 no tipo, 0,245 na severidade. E
das 505 vezes em que o modelo previu a classe intermediária, nenhuma estava
certa — precisão e recall zerados na mesma classe.

### Por classe, no tipo de falha

| Classe | Precisão | Recall | F1 |
| :--- | ---: | ---: | ---: |
| rolamento | 99,9 % | 100 % | 1,000 |
| desbalanceamento | 88,1 % | 98,8 % | 0,932 |
| desalinhamento | 96,5 % | 66,6 % | 0,788 |
| normal | 62,9 % | 76,3 % | 0,690 |

O recall sugeria que a condição normal ia razoavelmente; a precisão de 62,9 %
mostra que **37 % do que o modelo chama de "normal" não é** — 240 janelas de
desalinhamento classificadas como saudáveis.

### Dispersão entre partições

```
tipo de falha:  90,5 % ± 27,2 %   (min 0,0 % · max 100 %)
```

O desvio é estrutural, não ruído: o modelo acerta perto de 100 % em doze dos
catorze espécimes e **falha por completo em um** — o desalinhamento de nível 1.
O segundo pior é o desbalanceamento de 583 mg, com 70,6 %.

Os dois são **o grau mais brando de cada família**. O modelo identifica o tipo
com segurança assim que o defeito se manifesta, e não distingue defeito
incipiente de motor saudável.

### Comparação com a regra clássica

| Método | Acurácia no tipo |
| :--- | ---: |
| Regra de livro (1× / 2× / alta frequência) | 59,5 % |
| Regra empírica (protótipos ajustados no treino) | 63,0 % |
| Ensemble Random Forest + XGBoost | 88,7 % |

Achado que sustenta a escolha por protótipos empíricos: a literatura associa
desalinhamento a pico em 2× a rotação, mas neste dataset a proporção `p_2x` do
desalinhamento (0,178) é **menor** que a da condição normal (0,213) — a regra
procura no lugar errado.

### O vazamento, medido

| Protocolo | Tipo | Severidade |
| :--- | ---: | ---: |
| Aleatório por janela | 100,0 % | 100,0 % |
| Leave-one-load-out | 80,6 % | 95,3 % |
| **Leave-one-specimen-out** | **88,7 %** | **63,0 %** |

Os 100 % não são um erro que se evitou — são a **medida exata do vazamento** que
o split por espécime elimina.

Os protocolos estabelecem cenários de dificuldade distintos, fornecendo uma faixa
de referência metodológica para interpretar resultados futuros em campo. **Não**
se deve afirmar que o desempenho em campo ficará entre os dois valores.

---

## Metodologia — por que o split é por espécime

A unidade experimental independente não é a janela, nem a sessão de gravação, nem
a condição de carga: é o **espécime**, a montagem física da bancada. Os metadados
dos arquivos comprovam que cada defeito foi montado uma única vez e medido sob as
três cargas em sequência, com 6 a 43 minutos de intervalo — sem desmontagem. As
três sessões de um mesmo defeito compartilham rolamento, fixação e alinhamento, e
por isso vão inteiras para o mesmo lado da partição.

São 14 partições, uma por espécime de falha. As invariantes são verificadas em
tempo de execução (`_validate` em `ml/kaist/splits.py`): nenhum espécime nos dois
lados, cada sessão testada exatamente uma vez.

A evidência está nos próprios scripts: `04_evaluate.py` produz a tabela dos
protocolos e `12_metricas_completas.py`, as métricas por classe e a dispersão
entre partições. Ambos gravam CSV em `ml/data/interim/`.

---

## Arquivos para testar o sistema

```bash
python ml/scripts/11_gerar_amostras_demo.py
```

Gera dez amostras em `ml/data/demo_samples/` — sinais de 5 s, um canal de
vibração, recortados de **espécimes reservados**, excluídos do treino do modelo
de produção. A lista dos reservados fica gravada dentro do próprio artefato do
modelo e é devolvida por `GET /models/{versao}`, para que a afirmação "o modelo
nunca viu isto" seja verificável.

Na tela **Coletar**, envie o arquivo informando taxa de **25600** Hz e a carga que
consta do nome. Para ativar o critério de severidade por variação, envie antes
`2Nm_Normal.csv` marcado como **medição de referência**.

O `README.md` gerado na pasta descreve cada arquivo e o que esperar.

---

## Estrutura

```
docker-compose.yml              banco, API e interface
backend/
  app/
    api/v1/routes/              34 endpoints: auth, hierarquia, motores,
                                medições, alertas, modelos, inspeções, auditoria
    core/
      security.py               argon2id, JWT, CSRF em tempo constante
      alert_policy.py           8 regras nomeadas, avaliadas em ordem
    ml/predictor.py             inferência: severidade física é a primária
    models/                     12 tabelas SQLAlchemy
  alembic/versions/             7 migrations
  scripts/
    seed_admin.py               cria o primeiro usuário
    register_models.py          registra artefatos e o SHA-256 de cada um
frontend/src/                   React + TypeScript + Vite, 9 telas
ml/
  config.py                     caminhos e constantes
  kaist/
    sessions.py                 parsing e rotulagem por família de falha
    loaders.py                  leitura de .mat (vibração) e .tdms (corrente)
    features.py                 extração de características por janela
    severity.py                 indicadores normativos ISO 10816/20816
    physical_severity.py        severidade por critério físico
    splits.py                   leave-one-specimen-out
    decision.py                 matriz de decisão modelo × evidência física
  signals/
    readers.py                  adaptadores .mat/.tdms/.wav/.npy/.csv
    pipeline.py                 features por perfil de instrumentação
  scripts/
    01_extract_tdms.py          extrai os arquivos de corrente/temperatura
    02_inventory.py             inventário e sanidade física das 45 sessões
    03_extract_features.py      matriz de features (4.500 janelas × 97)
    04_evaluate.py              avaliação nos dois alvos e dois protocolos
    05_calibrate_decision.py    calibração da matriz de decisão
    07_generate_oof.py          predições out-of-fold
    08_single_channel_profile.py  features do perfil de canal único
    09_train_profiles.py        treina e serializa os dois perfis
    10_rule_vs_model.py         regra clássica × modelo
    11_gerar_amostras_demo.py   amostras dos espécimes reservados
    12_metricas_completas.py    dispersão, por classe, macro-F1, MCC
```

### Perfis de instrumentação

O mesmo código extrai features no treino e em produção. Se fossem dois caminhos,
o modelo receberia em campo features calculadas de forma diferente das do treino
— erro que não gera exceção, só diagnóstico errado.

| Perfil | Entrada | Features | Tipo |
| :--- | :--- | ---: | ---: |
| `kaist_full` | 4 acelerômetros + corrente | 97 | 88,7 % |
| `field_single` | 1 canal de vibração | 25 | 85,4 % |

O perfil é escolhido pela instrumentação enviada, não por configuração.

---

## Reproduzir do zero

Os sinais brutos (~7,6 GB) não são versionados. Baixe o dataset KAIST (Mendeley,
DOI 10.17632/ztmf3m7h5x), coloque os arquivos em `ml/data/raw/vibration/` e
`ml/data/raw/current_temp/`, e execute na ordem:

```bash
pip install -r backend/requirements.txt
```

```bash
python ml/scripts/02_inventory.py
```

```bash
python ml/scripts/03_extract_features.py
```

```bash
python ml/scripts/08_single_channel_profile.py
```

```bash
python ml/scripts/04_evaluate.py
```

```bash
python ml/scripts/09_train_profiles.py
```

```bash
python ml/scripts/07_generate_oof.py
```

```bash
python ml/scripts/12_metricas_completas.py
```

**As versões das bibliotecas de ML estão fixas no `requirements.txt`, e isso não
é preferência de estilo.** O artefato `.joblib` carrega árvores serializadas pelo
scikit-learn; abri-lo com uma versão diferente da que treinou emite
`InconsistentVersionWarning` e, nas palavras da própria biblioteca, "pode levar a
resultados inválidos" — um diagnóstico errado sem erro visível. Ao retreinar com
outras versões, atualizar o arquivo junto.

---

## Limitações conhecidas

- **Recall de WARNING = 0,0 %** sob leave-one-specimen-out. Os rótulos de
  severidade do dataset são administrativos, não físicos, e há um único espécime
  por nível — o modelo precisa graduar uma escala que nunca viu. Sob
  leave-one-load-out o mesmo recall é 85,8 %.
- **Espécime saudável único.** Nenhuma partição avalia generalização para uma
  máquina saudável nunca vista — limitação do dataset, comum a bancadas de
  laboratório.
- **Seleção de modelo sobre os folds de avaliação.** A inclusão dos indicadores
  normativos e a calibração da matriz de decisão foram decididas observando as
  métricas out-of-fold, o que as torna otimistas em grau não quantificado.
- **Sem geometria de rolamento.** O sistema não calcula BPFO, BPFI, BSF ou FTF a
  partir das dimensões do rolamento, e não usa fase entre mancais nem bandas
  laterais. Usa bandas de energia genéricas. É triagem automática, não
  substituição do analista de vibração.
- **Temperatura fora do modelo.** Sua variação entre sessões é ~7× maior que
  dentro de uma sessão, o que a torna uma impressão digital da gravação e não um
  sinal de falha.
- **Acústica fora do escopo.** O pacote original cobre apenas 5 das 45 sessões.

---

## Dataset

Jung, W. et al. (2023). *Vibration, acoustic, temperature, and motor current
dataset of rotating machine under varying operating conditions for fault
diagnosis.* Data in Brief. Mendeley Data, DOI 10.17632/ztmf3m7h5x.
