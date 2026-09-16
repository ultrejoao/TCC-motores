/**
 * Detalhamento de um motor: condicao atual, evolucao e historico.
 *
 * Os graficos mostram os indicadores normativos ao longo do tempo, e nao o
 * RMS de aceleracao bruto: a velocidade em mm/s e a grandeza que a ISO
 * 10816 avalia, e e muito menos sensivel a variacao de carga.
 */

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  CartesianGrid,
  Legend,
  ReferenceLine,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { put } from "../api/client";
import {
  ROTULO_FALHA,
  ROTULO_REGRA,
  type Alert,
  type Inspection,
  type MeasurementListItem,
  type MotorDetail,
  type Page,
} from "../api/types";
import {
  Carregando,
  Erro,
  Metrica,
  SeloCriticidade,
  SeloEvidencia,
  SeloSeveridade,
  Vazio,
  dataCurta,
  dataHora,
} from "../components/ui";
import EditarMotor from "../components/EditarMotor";
import FormaDeOnda from "../components/FormaDeOnda";
import RegistrarInspecao from "../components/RegistrarInspecao";
import { useApi } from "../hooks/useApi";

const CORES_GRAFICO = {
  v_rms: "#38bdf8",
  v_1x: "#a78bfa",
  a_hf: "#fb923c",
};

export default function Motor() {
  const { id } = useParams<{ id: string }>();
  const navegar = useNavigate();
  const [salvando, setSalvando] = useState(false);
  const [editando, setEditando] = useState(false);
  const [inspecionando, setInspecionando] = useState<MeasurementListItem | null>(null);
  const [pontoId, setPontoId] = useState<string | null>(null);

  const motor = useApi<MotorDetail>(id ? `/motors/${id}` : null);
  const medicoes = useApi<Page<MeasurementListItem>>(
    id ? `/motors/${id}/measurements?limit=60` : null,
  );
  const inspecoes = useApi<Inspection[]>(id ? `/inspections?motor_id=${id}` : null);
  const alertas = useApi<Page<Alert>>(
    id ? `/alerts?motor_id=${id}&status=OPEN` : null,
  );

  if (motor.carregando) return <Carregando linhas={6} />;
  if (motor.erro) return <Erro>{motor.erro.detail}</Erro>;
  if (!motor.dados) return null;

  const m = motor.dados;
  const historico = [...(medicoes.dados?.items ?? [])].reverse();

  const serie = historico.map((x) => ({
    id: x.id,
    data: dataCurta(x.collected_at),
    quando: x.collected_at,
    v_rms: x.iso_v_rms_mms,
    v_1x: x.iso_v_1x_mms,
    a_hf: x.iso_a_hf_g,
  }));

  // A medicao mais recente ja vem selecionada: o grafico de onda aparece sem
  // exigir descoberta, e clicar em outro ponto troca a selecao.
  const selecionada = serie.find((s) => s.id === pontoId) ?? serie[serie.length - 1];

  /** Resolver e terminal: a API recusa reabrir um alerta ja resolvido. */
  async function resolverAlerta(alertaId: string) {
    setSalvando(true);
    try {
      await put(`/alerts/${alertaId}`, { status: "RESOLVED" });
      alertas.recarregar();
      motor.recarregar();
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="pilha">
      <div>
        <div className="faint">
          {[m.plant_name, m.area_name, m.line_name].filter(Boolean).join(" › ") ||
            "sem local definido"}
        </div>
        <div className="linha" style={{ gap: "0.8rem", flexWrap: "wrap" }}>
          <h1>{m.tag}</h1>
          <SeloCriticidade valor={m.criticality} />
          <SeloSeveridade valor={m.last_severity} />
          {!editando && (
            <button
              className="secundario"
              onClick={() => setEditando(true)}
              style={{ marginLeft: "auto", padding: "0.35rem 0.8rem", fontSize: "0.85rem" }}
            >
              Editar cadastro
            </button>
          )}
        </div>
        <p className="dim" style={{ margin: "0.15rem 0 0" }}>{m.name}</p>
      </div>

      {editando && (
        <EditarMotor
          motor={m}
          aoSalvar={() => {
            setEditando(false);
            motor.recarregar();
          }}
          aoCancelar={() => setEditando(false)}
          aoExcluir={() => navegar("/planta")}
        />
      )}

      <div
        className="grade"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}
      >
        <div className="cartao">
          <Metrica rotulo="Medições" valor={m.measurement_count} />
        </div>
        <div className="cartao">
          <Metrica
            rotulo="Última coleta"
            valor={m.last_measurement_at ? dataCurta(m.last_measurement_at) : "—"}
          />
        </div>
        <div className="cartao">
          <Metrica
            rotulo="Diagnóstico"
            valor={
              m.last_is_baseline
                ? "Referência"
                : m.last_fault_type ? ROTULO_FALHA[m.last_fault_type] : "—"
            }
          />
        </div>
        <div className="cartao">
          <Metrica
            rotulo="Alertas abertos"
            valor={m.open_alerts}
            destaque={m.open_alerts > 0 ? "var(--failure)" : undefined}
          />
        </div>
      </div>

      {!m.has_baseline && (
        <div className="aviso info">
          Este motor não tem <strong>medição de referência</strong> registrada. Com
          uma referência em condição normal, o sistema passa a informar a variação
          percentual de cada indicador — por exemplo, “a vibração aumentou 180% em
          relação à condição normal conhecida deste motor”. Ao coletar com o motor
          sabidamente saudável, marque a medição como referência.
        </div>
      )}

      {(alertas.dados?.items.length ?? 0) > 0 && (
        <section className="cartao">
          <h2 style={{ marginBottom: "0.9rem" }}>Alertas abertos</h2>
          <div className="pilha" style={{ gap: "0.9rem" }}>
            {alertas.dados!.items.map((a) => (
              <div
                key={a.id}
                style={{
                  borderLeft: `3px solid var(--${a.severity === "FAILURE" ? "failure" : "warning"})`,
                  paddingLeft: "0.9rem",
                }}
              >
                <div className="linha" style={{ gap: "0.6rem", flexWrap: "wrap" }}>
                  <strong>{ROTULO_REGRA[a.rule] ?? a.rule}</strong>
                  <span className="mono faint">prioridade {a.priority_score.toFixed(0)}</span>
                  <SeloEvidencia
                    concorda={a.evidence_agreement}
                    tipoFisico={a.physical_type}
                  />
                </div>
                <p style={{ margin: "0.3rem 0" }}>{a.message}</p>

                {a.reasons.length > 0 && (
                  <ul className="faint" style={{ margin: "0.3rem 0", paddingLeft: "1.1rem" }}>
                    {a.reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                )}

                <div className="linha" style={{ gap: "0.5rem", marginTop: "0.5rem" }}>
                  <button
                    className="secundario"
                    disabled={salvando}
                    onClick={() => resolverAlerta(a.id)}
                    style={{ padding: "0.3rem 0.7rem", fontSize: "0.85rem" }}
                  >
                    Resolver
                  </button>
                  <span className="faint">{dataHora(a.created_at)}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="cartao">
        <h2 style={{ marginBottom: "0.3rem" }}>Evolução dos indicadores</h2>
        <p className="faint" style={{ marginTop: 0 }}>
          Velocidade conforme ISO 10816 (mm/s) e aceleração em alta frequência (g),
          que é o indicador sensível a falha de rolamento.
        </p>

        {serie.length < 2 ? (
          <Vazio>
            São necessárias ao menos duas medições para traçar a evolução.
          </Vazio>
        ) : (
          <div style={{ height: 280 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={serie}
                margin={{ top: 8, right: 8, bottom: 4, left: -18 }}
                style={{ cursor: "pointer" }}
                onClick={(estado: { activeTooltipIndex?: number }) => {
                  const i = estado?.activeTooltipIndex;
                  if (i != null && serie[i]) setPontoId(serie[i].id);
                }}
              >
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="data" stroke="var(--text-faint)" fontSize={12} />
                <YAxis
                  yAxisId="v"
                  stroke="var(--text-faint)"
                  fontSize={12}
                  label={{ value: "mm/s", angle: -90, position: "insideLeft",
                           fill: "var(--text-faint)", fontSize: 11 }}
                />
                <YAxis yAxisId="a" orientation="right" stroke="var(--text-faint)" fontSize={12} />
                {selecionada && (
                  <ReferenceLine
                    yAxisId="v"
                    x={selecionada.data}
                    stroke="var(--accent)"
                    strokeDasharray="4 3"
                  />
                )}
                <Tooltip
                  contentStyle={{
                    background: "var(--bg-elev-2)",
                    border: "1px solid var(--border-forte)",
                    borderRadius: 6,
                    fontSize: 13,
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line
                  yAxisId="v"
                  type="monotone"
                  dataKey="v_rms"
                  name="Velocidade RMS (mm/s)"
                  stroke={CORES_GRAFICO.v_rms}
                  strokeWidth={2}
                  dot={{ r: 2 }}
                />
                <Line
                  yAxisId="v"
                  type="monotone"
                  dataKey="v_1x"
                  name="Componente 1× (mm/s)"
                  stroke={CORES_GRAFICO.v_1x}
                  strokeWidth={2}
                  dot={{ r: 2 }}
                />
                <Line
                  yAxisId="a"
                  type="monotone"
                  dataKey="a_hf"
                  name="Alta frequência (g)"
                  stroke={CORES_GRAFICO.a_hf}
                  strokeWidth={2}
                  dot={{ r: 2 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {serie.length >= 2 && (
          <p className="faint" style={{ margin: "0.6rem 0 0", fontSize: "0.82rem" }}>
            Clique num ponto do gráfico para ver a forma de onda daquela coleta.
          </p>
        )}
      </section>

      {selecionada && (
        <FormaDeOnda
          key={selecionada.id}
          medicaoId={selecionada.id}
          quando={selecionada.quando}
        />
      )}

      <section className="cartao">
        <div className="linha" style={{ justifyContent: "space-between", marginBottom: "0.8rem" }}>
          <h2>Histórico de medições</h2>
          <Link to={`/coleta?motor=${m.id}`} className="faint">
            nova coleta →
          </Link>
        </div>

        {medicoes.carregando ? (
          <Carregando />
        ) : historico.length === 0 ? (
          <Vazio>Nenhuma medição registrada para este motor.</Vazio>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Coleta</th>
                  <th>Ref.</th>
                  <th>v RMS</th>
                  <th>1×</th>
                  <th>a HF</th>
                  <th>Zona</th>
                  <th>Diagnóstico</th>
                  <th>Carga</th>
                  <th>Inspeção</th>
                </tr>
              </thead>
              <tbody>
                {[...historico].reverse().map((x) => (
                  <tr key={x.id}>
                    <td>{dataHora(x.collected_at)}</td>
                    <td>{x.is_baseline && <span className="selo HEALTHY">ref.</span>}</td>
                    <td className="mono">{x.iso_v_rms_mms?.toFixed(3) ?? "—"}</td>
                    <td className="mono">{x.iso_v_1x_mms?.toFixed(4) ?? "—"}</td>
                    <td className="mono">{x.iso_a_hf_g?.toFixed(3) ?? "—"}</td>
                    <td className="mono">{x.iso_zone ?? "—"}</td>
                    <td>
                      {x.is_baseline ? (
                        <span className="faint">Referência — condição normal</span>
                      ) : x.fault_type ? (
                        ROTULO_FALHA[x.fault_type]
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="mono">{x.load_nm ?? "—"}</td>
                    <td>
                      {x.is_baseline ? (
                        <span className="faint">—</span>
                      ) : x.inspected ? (
                        <span className="faint">confirmada</span>
                      ) : x.prediction_id ? (
                        <button
                          className="secundario"
                          onClick={() => setInspecionando(x)}
                          style={{ padding: "0.2rem 0.6rem", fontSize: "0.8rem" }}
                        >
                          registrar
                        </button>
                      ) : (
                        <span className="faint">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {inspecionando && (
        <RegistrarInspecao
          motorId={m.id}
          predictionId={inspecionando.prediction_id}
          tipoPrevisto={inspecionando.fault_type}
          aoCancelar={() => setInspecionando(null)}
          aoRegistrar={() => {
            setInspecionando(null);
            medicoes.recarregar();
            inspecoes.recarregar();
          }}
        />
      )}

      {/* O laco fechado: o que o sistema diagnosticou contra o que se encontrou
          ao abrir a maquina. E a unica medida de acerto que nao vem do dataset
          que treinou o modelo. */}
      {inspecoes.dados && inspecoes.dados.length > 0 && (
        <section className="cartao">
          <h2 style={{ marginBottom: "0.7rem" }}>Inspeções de campo</h2>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Inspeção</th>
                  <th>Diagnosticado</th>
                  <th>Encontrado</th>
                  <th>Conferiu</th>
                  <th>Achados</th>
                </tr>
              </thead>
              <tbody>
                {inspecoes.dados.map((i) => (
                  <tr key={i.id}>
                    <td>{dataHora(i.performed_at)}</td>
                    <td>
                      {i.predicted_fault_type ? ROTULO_FALHA[i.predicted_fault_type] : "—"}
                    </td>
                    <td>
                      {i.confirmed_fault_type
                        ? ROTULO_FALHA[i.confirmed_fault_type]
                        : "não conclusivo"}
                    </td>
                    <td>
                      {i.agreement == null ? (
                        <span className="faint">—</span>
                      ) : (
                        <span
                          style={{
                            color: i.agreement ? "var(--healthy)" : "var(--failure)",
                          }}
                        >
                          {i.agreement ? "sim" : "não"}
                        </span>
                      )}
                    </td>
                    <td className="faint">{i.findings ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="cartao">
        <h2 style={{ marginBottom: "0.7rem" }}>Dados de placa</h2>
        <div
          className="grade"
          style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}
        >
          <div>
            <div className="faint">Fabricante</div>
            <div>{m.manufacturer ?? "—"}</div>
          </div>
          <div>
            <div className="faint">Modelo</div>
            <div>{m.model ?? "—"}</div>
          </div>
          <div>
            <div className="faint">Potência</div>
            <div>{m.power_kw ? `${m.power_kw} kW` : "—"}</div>
          </div>
          <div>
            <div className="faint">Rotação nominal</div>
            <div>{m.rated_rpm ? `${m.rated_rpm} rpm` : "—"}</div>
          </div>
          <div>
            <div className="faint">Polos</div>
            <div>{m.poles ?? "—"}</div>
          </div>
          <div>
            <div className="faint">Classe ISO 10816</div>
            <div>{m.iso_machine_class}</div>
          </div>
        </div>
      </section>
    </div>
  );
}
