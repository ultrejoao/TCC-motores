"""Caminhos e constantes do pipeline de dados KAIST."""

from pathlib import Path

# Pacotes originais baixados do Mendeley
KAIST_DOWNLOAD = Path(r"C:\Users\João Vitor\Downloads\DATA KAIST")
CURRENT_TEMP_ZIP = KAIST_DOWNLOAD / "current,temp.zip"
ACOUSTIC_ZIP = KAIST_DOWNLOAD / "acoustic.zip"   # apenas 5 sessoes 

ML_ROOT = Path(__file__).resolve().parent
DATA_RAW = ML_ROOT / "data" / "raw"              # sinais brutos
DATA_INTERIM = ML_ROOT / "data" / "interim"      #  features
ARTIFACTS = ML_ROOT / "artifacts"                # modelos serializados

VIBRATION_DIR = DATA_RAW / "vibration"           # 45 .mat  (4 acelerometros)
TDMS_DIR = DATA_RAW / "current_temp"             # 45 .tdms (3 corrente + 2 termopar)

# --- caracteristicas dos sinais --------------------------------------------
FS_VIBRATION = 25_600.0        # Hz
FS_CURRENT_TEMP = 25_608.19    # Hz

ROTATION_HZ = 50.15            # 3009 rpm, medido por FFT (motor de 2 polos)

# Vibracao: 4 acelerometros, gravados em MKS (m/s^2). Fator p/ converter em g.
VIBRATION_CHANNELS = ["acc1", "acc2", "acc3", "acc4"]
MS2_TO_G = 1.0 / 9.80665

# Corrente/temperatura: grupo "Log" do TDMS.
TDMS_GROUP = "Log"
TDMS_CHANNEL_MAP = {
    "cDAQ9185-1F486B5Mod1/ai0": "temp1",      # termopar mancal 1 (degC)
    "cDAQ9185-1F486B5Mod1/ai1": "temp2",      # termopar mancal 2 (degC)
    "cDAQ9185-1F486B5Mod2/ai0": "current_r",  # fase R (A)
    "cDAQ9185-1F486B5Mod2/ai2": "current_s",  # fase S (A)
    "cDAQ9185-1F486B5Mod2/ai3": "current_t",  # fase T (A) 
}

# Unica fase disponivel em 100% das sessoes
CURRENT_CHANNEL = "current_r"

# Artefatos por perfil de instrumentacao (ver ml/signals/pipeline.py).
MODEL_ARTIFACTS = {
    "kaist_full": ARTIFACTS / "model_kaist_full_v1.joblib",
    "field_single": ARTIFACTS / "model_field_single_v1.joblib",
}

# Classe de maquina ISO 10816-1 assumida para a bancada do KAIST
ISO_MACHINE_CLASS = "I"

for _d in (DATA_RAW, DATA_INTERIM, ARTIFACTS, VIBRATION_DIR, TDMS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
