/**
 * Coleta em campo — desenhada primeiro para celular.
 *
 * O tecnico esta de pe, ao lado da maquina, muitas vezes com luva. Por isso o
 * formulario e uma coluna unica, os alvos de toque sao grandes, e o resultado
 * do diagnostico aparece na mesma tela logo apos o envio: ele precisa saber se
 * deve agir antes de sair de perto do motor.
 */

import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, upload } from "../api/client";
import {
  ROTULO_FALHA,
  type MeasurementWithPrediction,
  type MotorDetail,
  type Page,
} from "../api/types";
import {
  BarraConfianca,
  Carregando,
  SeloEvidencia,
  SeloSeveridade,
} from "../components/ui";
import FormaDeOnda from "../components/FormaDeOnda";
import { useApi } from "../hooks/useApi";

/** Formatos que trazem a taxa de amostragem dentro do proprio arquivo. */
const AUTODESCRITIVOS = [".mat", ".tdms", ".wav"];

export default function Coleta() {
  const [params] = useSearchParams();
  const motores = useApi<Page<MotorDetail>>("/motors?limit=200");

  const [motorId, setMotorId] = useState(params.get("motor") ?? "");
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [taxa, setTaxa] = useState("25600");
  const [unidade, setUnidade] = useState("m/s^2");
  const [carga, setCarga] = useState("");
  const [rpm, setRpm] = useState("");
  const [temperatura, setTemperatura] = useState("");
  const [referencia, setReferencia] = useState(false);
  const [observacoes, setObservacoes] = useState("");

  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [resultado, setResultado] = useState<MeasurementWithPrediction | null>(null);

  const sufixo = arquivo ? arquivo.name.slice(arquivo.name.lastIndexOf(".")).toLowerCase() : "";
  const precisaTaxa = arquivo !== null && !AUTODESCRITIVOS.includes(sufixo);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    if (!arquivo || !motorId) return;

    setErro(null);
    setEnviando(true);
    setResultado(null);

    const contexto: Record<string, unknown> = {
      motor_id: motorId,
      is_baseline: referencia,
    };
    if (precisaTaxa) contexto.sample_rate_hz = Number(taxa);
    if (precisaTaxa && unidade !== "m/s^2") contexto.unit = unidade;
    if (carga) contexto.load_nm = Number(carga);
    if (rpm) contexto.rpm = Number(rpm);
    if (temperatura) contexto.temperature_c = Number(temperatura);
    if (observacoes) contexto.notes = observacoes;

    const dados = new FormData();
    dados.append("file", arquivo);
    dados.append("context", JSON.stringify(contexto));

    try {
      const r = await upload<MeasurementWithPrediction>("/measurements", dados);
      setResultado(r);
      setArquivo(null);
      setReferencia(false);
      setObservacoes("");
    } catch (ex) {
      setErro(ex instanceof ApiError ? ex.detail : "Falha ao enviar a medição.");
    } finally {
      setEnviando(false);
    }
  }

  if (motores.carregando) return <Carregando linhas={5} />;

  const p = resultado?.prediction;

  return (
    <div className="pilha" style={{ maxWidth: 560, margin: "0 auto" }}>
      <div>
        <h1>Nova coleta</h1>
        <p className="faint" style={{ margin: "0.2rem 0 0" }}>
          Envie o sinal coletado com o analisador. O diagnóstico aparece aqui
          mesmo, logo após o envio.
        </p>
      </div>

      {resultado && p && (
        <section
          className="cartao"
          style={{
            borderLeft: `4px solid var(--${
              p.severity === "FAILURE" ? "failure" : p.severity === "WARNING" ? "warning" : "healthy"
            })`,
          }}
        >
          <div className="linha" style={{ gap: "0.7rem", flexWrap: "wrap" }}>
            <SeloSeveridade valor={p.severity} />
            {!resultado.is_baseline && (
              <SeloEvidencia concorda={p.evidence_agreement} tipoFisico={p.physical_type} />
            )}
          </div>

          <h2 style={{ margin: "0.7rem 0 0.2rem" }}>
            {resultado.is_baseline ? "Referência — condição normal" : ROTULO_FALHA[p.fault_type]}
          </h2>

          {resultado.is_baseline && (
            <p className="faint" style={{ margin: "0.3rem 0 0" }}>
              Medição registrada como condição normal deste motor. As próximas coletas
              serão comparadas com ela.
            </p>
          )}

          {/* Duas origens distintas, exibidas como tais: o modelo responde o
              TIPO; a severidade vem de critério físico normativo. */}
          {!resultado.is_baseline && (
          <div style={{ margin: "0.8rem 0" }}>
            <div className="faint" style={{ marginBottom: "0.25rem" }}>
              Tipo de falha — identificado pelo modelo
            </div>
            <BarraConfianca
              valor={p.fault_type_probabilities[p.fault_type] ?? p.confidence}
            />

            <div className="faint" style={{ margin: "0.6rem 0 0.25rem" }}>
              Confiança no diagnóstico do tipo
            </div>
            <BarraConfianca valor={p.confidence} />
          </div>
          )}

          <div
            style={{
              margin: "0.9rem 0",
              padding: "0.75rem",
              background: "var(--bg)",
              borderRadius: "var(--radius-sm)",
            }}
          >
            <div className="linha" style={{ gap: "0.6rem", flexWrap: "wrap" }}>
              <span className="faint">Severidade por critério físico</span>
              <SeloSeveridade valor={p.severity} />
              {p.ratio_to_baseline !== null && (
                <span className="mono">{p.ratio_to_baseline.toFixed(1)}× a referência</span>
              )}
            </div>
            {p.severity_explanation && (
              <p className="faint" style={{ margin: "0.4rem 0 0" }}>
                {p.severity_explanation}
              </p>
            )}
            {p.severity_criterion === "ISO_10816_ZONA" && (
              <div className="aviso atencao" style={{ marginTop: "0.5rem" }}>
                Sem medição de referência deste motor, a avaliação usa apenas a
                magnitude absoluta — critério que subestima degradação incipiente.
                Registre uma medição de referência para diagnóstico mais sensível.
              </div>
            )}
          </div>

          <p style={{ margin: "0.6rem 0" }}>{p.recommendation}</p>

          {resultado.profile_note && (
            <div className="aviso atencao" style={{ marginTop: "0.6rem" }}>
              {resultado.profile_note}
            </div>
          )}

          {p.baseline_comparison && (
            <div style={{ marginTop: "0.8rem" }}>
              <div className="faint">Comparação com a referência deste motor</div>
              {Object.entries(p.baseline_comparison)
                .filter(([k]) => k.endsWith("_change_pct"))
                .map(([k, v]) => (
                  <div key={k} className="linha" style={{ justifyContent: "space-between" }}>
                    <span className="mono faint">{k.replace("_change_pct", "")}</span>
                    <strong style={{ color: v > 0 ? "var(--warning)" : "var(--healthy)" }}>
                      {v > 0 ? "+" : ""}
                      {v.toFixed(0)}%
                    </strong>
                  </div>
                ))}
            </div>
          )}

          <div className="linha" style={{ gap: "0.6rem", marginTop: "1rem", flexWrap: "wrap" }}>
            <Link to={`/motores/${resultado.motor_id}`}>
              <button className="secundario">Ver o motor</button>
            </Link>
            <button className="secundario" onClick={() => setResultado(null)}>
              Nova coleta
            </button>
          </div>

          <div className="faint" style={{ marginTop: "0.8rem" }}>
            Zona ISO {resultado.iso_zone} · perfil {resultado.profile} · modelo{" "}
            {resultado.model_version} · {p.inference_ms?.toFixed(0)} ms
          </div>
        </section>
      )}

      {/* O sinal que originou o diagnostico, logo abaixo dele: o tecnico ve a
          medicao e a leitura na mesma tela, sem navegar. */}
      {resultado && <FormaDeOnda medicaoId={resultado.id} />}

      {!resultado && (
        <form onSubmit={enviar} className="cartao">
          {erro && (
            <div className="aviso erro" style={{ marginBottom: "1rem" }}>
              {erro}
            </div>
          )}

          <div className="campo">
            <label htmlFor="motor">Motor</label>
            <select
              id="motor"
              value={motorId}
              onChange={(e) => setMotorId(e.target.value)}
              required
            >
              <option value="">selecione…</option>
              {motores.dados?.items.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.tag} — {m.name}
                </option>
              ))}
            </select>
          </div>

          <div className="campo">
            <label htmlFor="arquivo">Arquivo de sinal</label>
            <input
              id="arquivo"
              type="file"
              accept=".csv,.mat,.tdms,.npy,.wav,.txt"
              onChange={(e) => setArquivo(e.target.files?.[0] ?? null)}
              required
            />
            <div className="faint" style={{ marginTop: "0.3rem" }}>
              {arquivo
                ? `${arquivo.name} · ${(arquivo.size / 1e6).toFixed(1)} MB`
                : "Aceita .csv, .mat, .tdms, .npy e .wav"}
            </div>
          </div>

          {precisaTaxa && (
            <div className="aviso info" style={{ marginBottom: "0.9rem" }}>
              O formato <span className="mono">{sufixo}</span> não informa a taxa de
              amostragem. Sem ela nenhuma frequência pode ser calculada, então o
              valor precisa vir do analisador.
            </div>
          )}

          {precisaTaxa && (
            <>
              <div className="campo">
                <label htmlFor="taxa">Taxa de amostragem (Hz)</label>
                <input
                  id="taxa"
                  type="number"
                  value={taxa}
                  onChange={(e) => setTaxa(e.target.value)}
                  min={100}
                  required
                />
              </div>
              <div className="campo">
                <label htmlFor="unidade">Unidade do sinal</label>
                <select
                  id="unidade"
                  value={unidade}
                  onChange={(e) => setUnidade(e.target.value)}
                >
                  <option value="m/s^2">m/s² (aceleração)</option>
                  <option value="g">g (aceleração)</option>
                </select>
              </div>
            </>
          )}

          <div
            className="grade"
            style={{ gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))" }}
          >
            <div className="campo">
              <label htmlFor="carga">Carga (Nm)</label>
              <input
                id="carga"
                type="number"
                step="any"
                value={carga}
                onChange={(e) => setCarga(e.target.value)}
              />
            </div>
            <div className="campo">
              <label htmlFor="rpm">Rotação (rpm)</label>
              <input
                id="rpm"
                type="number"
                step="any"
                value={rpm}
                onChange={(e) => setRpm(e.target.value)}
              />
            </div>
            <div className="campo">
              <label htmlFor="temp">Temperatura (°C)</label>
              <input
                id="temp"
                type="number"
                step="any"
                value={temperatura}
                onChange={(e) => setTemperatura(e.target.value)}
              />
            </div>
          </div>

          <div className="campo">
            <label htmlFor="obs">Observações</label>
            <textarea
              id="obs"
              rows={2}
              value={observacoes}
              onChange={(e) => setObservacoes(e.target.value)}
              placeholder="ponto de medição, condição de operação…"
            />
          </div>

          <label
            className="linha"
            style={{
              gap: "0.6rem",
              padding: "0.7rem",
              background: "var(--bg)",
              borderRadius: "var(--radius-sm)",
              cursor: "pointer",
              marginBottom: "1rem",
            }}
          >
            <input
              type="checkbox"
              checked={referencia}
              onChange={(e) => setReferencia(e.target.checked)}
              style={{ width: 18, height: 18, flexShrink: 0 }}
            />
            <span>
              <strong>Esta é uma medição de referência</strong>
              <div className="faint">
                Marque apenas com o motor sabidamente em condição normal. Passa a
                ser a base de comparação deste motor.
              </div>
            </span>
          </label>

          <button
            type="submit"
            disabled={enviando || !arquivo || !motorId}
            style={{ width: "100%", padding: "0.85rem" }}
          >
            {enviando ? "Analisando o sinal…" : "Enviar e diagnosticar"}
          </button>
        </form>
      )}
    </div>
  );
}
